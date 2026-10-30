"""Refresh exam notices from all registered department boards."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from . import db
from .public_catalog import CATALOG, PublicFetcher
from .crawler import parse_listing, parse_detail
from .attachments import register, run
from .exam_matching import EXAM, matches
from sqlalchemy import select

def boards(catalog, department=None):
    seen = set()
    for source in catalog['sources']:
        if not source.get('department') or source['kind'] != 'board': continue
        if department and source['department'] != department: continue
        key = (source['department'], source['url'])
        if key not in seen:
            seen.add(key)
            yield source

def update(catalog_path=CATALOG, department=None, year=None, term=None,
           kind='중간고사', max_pages=5, index=True):
    today = datetime.now(ZoneInfo('Asia/Seoul'))
    year, term = year or today.year, term or (1 if today.month < 8 else 2)
    catalog = json.loads(Path(catalog_path).read_text(encoding='utf-8'))
    sources = list(boards(catalog, department))
    if not sources: raise ValueError('No department boards registered for this selection')
    departments = sorted({s['department'] for s in catalog['sources'] if s.get('department')
                          and (not department or s['department'] == department)})
    report = {d: dict(boards=0, notices=0, created=0, updated=0, unchanged=0, failed=0, attachment_failed=0, unreadable_attachments=0, image_notices=0, scan_limited=False) for d in departments}
    fetcher, processed = PublicFetcher(), set()
    try:
        try:
            from .exam_calendar import refresh
            print(json.dumps({'academic_calendar': refresh(fetcher)}, ensure_ascii=False), flush=True)
        except Exception as exc:
            db.record_crawl('학사일정', 'failed', type(exc).__name__)
            print(json.dumps({'academic_calendar': 'failed', 'error': type(exc).__name__}), flush=True)
        for source in sources:
            info = report[source['department']]
            info['boards'] += 1
            seen = set()
            try:
                for page in range(1, max_pages + 1):
                    soup, final = fetcher.fetch(source['url'] + f'&page={page}')
                    fresh = [i for i in parse_listing(soup, final) if i['url'] not in seen]
                    if not fresh: break
                    seen.update(i['url'] for i in fresh)
                    for item in fresh:
                        key = (source['department'], item['url'])
                        if key in processed or not EXAM.search(item['title']): continue
                        try:
                            detail, _ = fetcher.fetch(item['url'])
                            parsed = parse_detail(detail, item)
                            if not matches(parsed['title'], parsed['content'], parsed['published_at'], year, term, kind): continue
                            saved = db.save_notice(source=source['department'], source_type='notice', category=source['category'], **parsed)
                            info[saved] += 1
                            print(json.dumps({'department':source['department'], 'title':parsed['title'],
                                              'url':parsed['url'], 'status':saved}, ensure_ascii=False), flush=True)
                            register(detail, item['url'])
                            info['notices'] += 1
                            processed.add(key)
                            result = run(parent_url=item['url'])
                            info['attachment_failed'] += result['failed'] + result['parent_failed']
                            with db.session_scope() as session:
                                parent = session.scalar(select(db.Notice).where(db.Notice.url_hash == db.digest(item['url'])))
                                statuses = list(session.scalars(select(db.Attachment.status).where(db.Attachment.parent_id == parent.id, db.Attachment.status != 'removed')))
                            info['unreadable_attachments'] += sum(status != 'ok' for status in statuses)
                            if detail.select('#boardContents img, .board-view-content img'):
                                info['image_notices'] += 1
                        except Exception as exc:
                            info['failed'] += 1
                            db.record_crawl(source['department'], 'failed', f"exam {item['url']}: {type(exc).__name__}")
                else:
                    info['scan_limited'] = True
            except Exception as exc:
                info['failed'] += 1
                db.record_crawl(source['department'], 'failed', f"exam {source['url']}: {type(exc).__name__}")
            print(json.dumps({'department': source['department'], **info}, ensure_ascii=False), flush=True)
    finally:
        fetcher.close()
    for name, info in report.items():
        info['status'] = ('board_not_registered' if not info['boards'] else
                          'partial' if info['failed'] or info['attachment_failed'] or info['unreadable_attachments'] or info['image_notices'] or info['scan_limited'] else
                          'collected' if info['notices'] else 'not_found_in_scanned_pages')
        # CrawlLog.status is VARCHAR(20); detailed coverage belongs in message.
        db.record_crawl(name, 'success' if info['status'] == 'collected' else 'partial',
                        json.dumps({'year': year, 'term': term, 'kind': kind, **info}))
    print(json.dumps({'exam_coverage': report}, ensure_ascii=False), flush=True)
    if index:
        from .ingest_notices_to_context import ingest_chunks
        from .ingest_context_to_chroma import ingest_vectors
        print(ingest_chunks(), flush=True)
        print(ingest_vectors(), flush=True)
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--department')
    parser.add_argument('--year', type=int)
    parser.add_argument('--term', type=int, choices=[1, 2])
    parser.add_argument('--kind', choices=['중간고사', '기말고사'], default='중간고사')
    parser.add_argument('--max-pages', type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.max_pages <= 100: parser.error('max-pages must be 1..100')
    db.init_db()
    with db.maintenance_lock(): update(**vars(args))
