"""Public attachments -> page documents -> existing MySQL/Chroma RAG pipeline."""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from sqlalchemy import delete, select
from . import db
from .public_catalog import PublicFetcher, BLOCKED

MAX_BYTES = 20 * 1024 * 1024


def file_url(url):
    try:
        p = urlsplit(url)
        host = (p.hostname or '').lower()
        return (p.scheme == 'https' and not p.username and not p.password and p.port in (None, 443)
                and (host == 'donga.ac.kr' or host.endswith('.donga.ac.kr')) and host not in BLOCKED
                and not re.search(r'login|logout|member|sso|delete|write|modify', p.path, re.I))
    except ValueError:
        return False


def discover(soup, parent_url):
    result = {}
    # Only content areas, never site-wide navigation or arbitrary script execution.
    for a in soup.select('.bdAttachFiles a[href], .bdViewFiles a[href], #boardContents a[href], .board-view-content a[href], .contents_view_wrap a[href], #cont a[href]'):
        href = a.get('href', '').strip()
        if not href or href.startswith(('#', 'javascript:')):
            continue
        url = urljoin(parent_url, href)
        name = a.get_text(' ', strip=True) or a.get('download') or urlsplit(url).path.rsplit('/', 1)[-1]
        name = re.sub(r'\s+', ' ', name).strip()
        if file_url(url) and (re.search(r'\.(pdf|hwp|hwpx|docx?|xlsx?|pptx?|zip)(?:\b|$)', name + ' ' + url, re.I)
                              or re.search(r'download|fileDown', urlsplit(url).path, re.I)):
            p = urlsplit(url)
            url = urlunsplit((p.scheme, p.netloc, p.path, p.query, ''))
            result[url] = name[:1000]
    return result


def remove_pages(session, attachment_id):
    ids = list(session.scalars(select(db.AttachmentPage.notice_id).where(db.AttachmentPage.attachment_id == attachment_id)))
    if ids:
        session.execute(delete(db.ContextChunk).where(db.ContextChunk.source_id.in_(ids)))
        session.execute(delete(db.AttachmentPage).where(db.AttachmentPage.notice_id.in_(ids)))
        session.execute(delete(db.Notice).where(db.Notice.id.in_(ids)))


def register(soup, parent_url):
    links = discover(soup, parent_url)
    with db.session_scope() as session:
        parent = session.scalar(select(db.Notice).where(db.Notice.url_hash == db.digest(parent_url)))
        if parent is None:
            return
        existing = list(session.scalars(select(db.Attachment).where(db.Attachment.parent_id == parent.id)))
        for row in existing:
            if row.url not in links:
                remove_pages(session, row.id)
                row.status = 'removed'
                row.message = 'Link no longer present on verified parent page'
        for url, name in links.items():
            key = db.digest(str(parent.id) + '|' + url)
            row = session.get(db.Attachment, key)
            if row is None:
                session.add(db.Attachment(id=key, parent_id=parent.id, url=url, filename=name))
            else:
                if row.filename != name:
                    row.parent_hash = None
                row.filename = name
                if row.status == 'removed':
                    row.status = 'pending'
                    row.file_hash = None


class AttachmentFetcher(PublicFetcher):
    def download(self, url):
        for _ in range(6):
            if not file_url(url):
                raise ValueError('not_public_official_file')
            p = urlsplit(url)
            origin = f'https://{p.netloc}'
            if origin not in self.robots:
                response = self._get(origin + '/robots.txt')
                if response.status_code == 404:
                    lines = []
                else:
                    response.raise_for_status()
                    if '<html' in response.text[:1000].lower():
                        raise ValueError('robots_response_is_html')
                    lines = response.text.splitlines()
                robot = RobotFileParser(); robot.parse(lines); self.robots[origin] = robot
            if not self.robots[origin].can_fetch(self.agent, url):
                raise ValueError('robots_disallowed')
            time.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            with self.client.stream('GET', url) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    url = urljoin(url, response.headers['location'])
                    continue
                response.raise_for_status()
                if int(response.headers.get('content-length', '0')) > MAX_BYTES:
                    raise ValueError('file_too_large')
                chunks = []; size = 0; started = time.monotonic()
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES or time.monotonic() - started > 60:
                        raise ValueError('download_limit')
                    chunks.append(chunk)
                return b''.join(chunks)
        raise ValueError('too_many_redirects')


def extract(blob):
    if blob.startswith(b'PK'):
        from .exam_xlsx import extract_exam_xlsx
        return extract_exam_xlsx(blob)
    worker = subprocess.run([sys.executable, '-m', 'app.attachment_extract'], input=blob,
                            capture_output=True, timeout=90, check=False)
    if worker.returncode:
        raise ValueError(worker.stderr.decode('utf-8', errors='replace')[-300:])
    return json.loads(worker.stdout)


def save_pages(attachment_id, file_hash, pages):
    with db.session_scope() as session:
        attachment = session.get(db.Attachment, attachment_id)
        parent = session.get(db.Notice, attachment.parent_id)
        old = {p.page_number: p for p in session.scalars(select(db.AttachmentPage).where(db.AttachmentPage.attachment_id == attachment_id))}
        keep = set()
        for page in pages:
            if page['status'] != 'ok':
                continue
            number = page['page']; keep.add(number)
            label = page.get('label', f'PDF {number}쪽')
            title = f'{parent.title[:550]} · {attachment.filename[:350]} · {label}'
            content = f'첨부파일: {attachment.filename}\n{label}\n원문 공지: {parent.title}\n\n{page["text"]}'
            url = attachment.url + f'#page={number}&donga_parent={parent.id}'
            signature = db.digest(json.dumps([title, content, parent.category, str(parent.published_at)], ensure_ascii=False))
            row = session.get(db.Notice, old[number].notice_id) if number in old else None
            if row is None:
                row = db.Notice(url=url, url_hash=db.digest(url))
                session.add(row)
            row.source = parent.source; row.source_type = 'attachment'; row.category = parent.category
            row.title = title; row.content = content; row.published_at = parent.published_at
            row.content_hash = signature; row.crawled_at = db.utcnow()
            session.flush()
            if number not in old:
                session.add(db.AttachmentPage(notice_id=row.id, attachment_id=attachment_id, page_number=number))
        for number, page in old.items():
            if number not in keep:
                session.execute(delete(db.ContextChunk).where(db.ContextChunk.source_id == page.notice_id))
                session.delete(page)
                session.flush()
                session.execute(delete(db.Notice).where(db.Notice.id == page.notice_id))
        attachment.file_hash = file_hash
        attachment.parent_hash = parent.content_hash
        attachment.status = 'ok' if len(keep) == len(pages) else 'partial' if keep else 'ocr_required'
        attachment.message = json.dumps({'pages': len(pages), 'readable_pages': len(keep),
                                        'unreadable_pages': [p['page'] for p in pages if p['status'] != 'ok']})
        attachment.checked_at = db.utcnow()


def process(attachment_id, fetcher):
    with db.session_scope() as session:
        item = session.get(db.Attachment, attachment_id)
        parent_hash = session.get(db.Notice, item.parent_id).content_hash
    try:
        # Do not mistake a login/error HTML response for an attachment.
        blob = fetcher.download(item.url)
        if not blob.startswith(b'%PDF-') and not (blob.startswith(b'PK') and re.search(r'\.xlsx\b', item.filename, re.I)):
            status = 'unsupported' if blob.startswith((b'PK', b'\xd0\xcf\x11\xe0')) else 'invalid_file'
            raise ValueError(status + ': PDF only; HWP/HWPX/images need another extractor')
        signature = hashlib.sha256(blob).hexdigest()
        if signature == item.file_hash and parent_hash == item.parent_hash and item.status in ('ok', 'partial', 'ocr_required'):
            with db.session_scope() as session:
                session.get(db.Attachment, item.id).checked_at = db.utcnow()
            return 'unchanged'
        pages = extract(blob)
        save_pages(item.id, signature, pages)
        return 'extracted'
    except Exception as exc:
        with db.session_scope() as session:
            row = session.get(db.Attachment, item.id)
            row.status = 'unsupported' if str(exc).startswith('unsupported') else 'failed'
            row.message = (type(exc).__name__ + ': ' + str(exc))[:1000]
            row.checked_at = db.utcnow()
        return 'failed'


def run(parent_url=None, limit=20, category=None):
    fetcher = AttachmentFetcher()
    counts = {'parents': 0, 'parent_failed': 0, 'extracted': 0, 'unchanged': 0, 'failed': 0}
    try:
        with db.session_scope() as session:
            query = select(db.Notice).where(db.Notice.source_type.in_(['notice', 'static']))
            if parent_url: query = query.where(db.Notice.url == parent_url)
            if category: query = query.where(db.Notice.category == category)
            parents = list(session.scalars(query.order_by(db.Notice.crawled_at.desc(), db.Notice.id.desc()).limit(limit)))
        if parent_url and not parents:
            raise ValueError('Parent notice not in DB; crawl this notice first, then retry attachments.')
        for parent in parents:
            try:
                soup, _ = fetcher.fetch(parent.url)
                # A 200 error page must not retire previously collected files.
                if parent.source_type == 'notice':
                    from .crawler import parse_detail
                    parse_detail(soup, {'url': parent.url, 'published_at': parent.published_at})
                else:
                    from .crawl_public import extract_static
                    extract_static(soup)
                register(soup, parent.url)
                counts['parents'] += 1
            except Exception as exc:
                counts['parent_failed'] += 1
                db.record_crawl(parent.title, 'failed', 'attachment discovery: ' + str(exc))
                continue
            with db.session_scope() as session:
                ids = list(session.scalars(select(db.Attachment.id).where(db.Attachment.parent_id == parent.id, db.Attachment.status != 'removed')))
            for key in ids:
                result = process(key, fetcher); counts[result] += 1
                print(json.dumps({'attachment_id': key, 'status': result}), flush=True)
    finally:
        fetcher.close()
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', help='Existing parent notice URL')
    parser.add_argument('--category')
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000: parser.error('limit must be 1..10000')
    db.init_db()
    with db.maintenance_lock():
        print(run(args.url, args.limit, args.category))
