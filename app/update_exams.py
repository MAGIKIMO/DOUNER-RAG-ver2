"""Refresh current computer department exam notices and both RAG stores."""
from . import db
from .public_catalog import PublicFetcher
from .crawler import parse_listing, parse_detail
from .attachments import register, run
from datetime import datetime
from zoneinfo import ZoneInfo

URL = 'https://computer.donga.ac.kr/computer/CMS/Board/Board.do?mCode=MN044'


def update():
    fetcher = PublicFetcher()
    found = {}
    today = datetime.now(ZoneInfo('Asia/Seoul'))
    term = '1학기' if today.month < 8 else '2학기'
    try:
        for page in range(1, 4):
            soup, _ = fetcher.fetch(URL + f'&page={page}')
            for item in parse_listing(soup, URL):
                if all(word in item['title'] for word in ('중간고사', '시간표', str(today.year), term)):
                    found[item['url']] = item
        if not found:
            raise RuntimeError('No exam schedule notices found; check board selectors.')
        for item in found.values():
            soup, _ = fetcher.fetch(item['url'])
            parsed = parse_detail(soup, item)
            status = db.save_notice(source='컴퓨터공학과 공지', source_type='notice', category='컴퓨터공학과', **parsed)
            register(soup, item['url'])
            print({'notice': parsed['title'], 'status': status}, flush=True)
            result = run(parent_url=item['url'])
            print(result, flush=True)
            if result['failed'] or result['parent_failed']:
                raise RuntimeError('Attachment refresh incomplete; review output before retrying.')
    finally:
        fetcher.close()
    from .ingest_notices_to_context import ingest_chunks
    from .ingest_context_to_chroma import ingest_vectors
    print(ingest_chunks(), flush=True)
    print(ingest_vectors(), flush=True)


if __name__ == '__main__':
    db.init_db()
    with db.maintenance_lock():
        update()
