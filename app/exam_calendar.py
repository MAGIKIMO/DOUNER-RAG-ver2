"""Use verified university calendar rows without claiming a department timetable."""
import re
from sqlalchemy import select
from . import db
from .document_context import as_document

URL = 'https://www.donga.ac.kr/community/academic-calendar'
LEGACY_URL = 'https://www.donga.ac.kr/kor/CMS/Contents/Contents.do?mCode=MN173'


def extract_calendar(soup):
    """Read only the year-labelled academic table, not the monthly widget."""
    from bs4 import BeautifulSoup
    from .life_content import extract
    blocks = []
    for table in soup.select('table'):
        heading = table.find_previous(['h2', 'h3', 'h4', 'h5'])
        if not heading or not re.search(r'20\d{2}\s*학년도\s*학사일정', heading.get_text()):
            continue
        headers = {c.get_text(strip=True) for c in table.select('thead th')}
        if not {'업무', '기간'} <= headers:
            continue
        wrapped = BeautifulSoup('<div id="cont">' + str(heading) + str(table) + '</div>', 'html.parser')
        blocks.append(extract(wrapped))
    if blocks:
        return '\n'.join(blocks)
    content = extract(soup)
    if not re.search(r'20\d{2}\s*학년도\s*학사일정', content):
        raise ValueError('academic_calendar_heading_missing')
    return content


def record():
    with db.session_scope() as session:
        return session.scalar(select(db.Notice).where(
            db.Notice.url_hash.in_([db.digest(URL), db.digest(LEGACY_URL)])
        ).order_by(db.Notice.crawled_at.desc(), db.Notice.id.desc()))


def refresh(fetcher):
    soup, _ = fetcher.fetch(URL)
    content = extract_calendar(soup)
    from .calendar_chat import rows
    if not rows(content):
        raise ValueError('academic_calendar_rows_missing')
    return db.save_notice(source='동아대학교 공식홈페이지', source_type='static',
                          category='학사안내', title='학사일정', content=content, url=URL)


def evidence(year, term, kind):
    row = record()
    if row is None:
        return None
    # The original HTML has parallel lists; life_content preserves date/event
    # associations. Never infer a date from a different row or academic year.
    active_year = None
    lines = []
    event = re.compile(r'제?\s*' + re.escape(str(term)) + r'\s*학기\s*'
                       + ('기말' if '기말' in kind else '중간') + r'\s*(?:시험|고사)')
    for line in row.content.splitlines():
        heading = re.search(r'(20\d{2})\s*학년도\s*학사일정', line)
        if heading:
            active_year = heading[1]
        if active_year == str(year) and event.search(line) and '|' in line:
            dates = re.findall(r'(20\d{2})\s*\.', line)
            if dates and all(date == str(year) for date in dates):
                lines.append(line)
    if not lines:
        return None
    doc = as_document(row)
    doc.chunk_text = f'{year}학년도 학교 공통 학사일정\n' + '\n'.join(lines)
    doc.chunk_text += '\n학교 공통 시험 기간이며 학과별·과목별 시험 시간표를 뜻하지 않습니다.'
    return doc


if __name__ == '__main__':
    from .public_catalog import PublicFetcher
    db.init_db()
    fetcher = PublicFetcher()
    try:
        with db.maintenance_lock():
            print({'academic_calendar': refresh(fetcher)})
    finally:
        fetcher.close()
