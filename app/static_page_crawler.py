from .crawl_common import Fetcher, clean_text, first_node
from .db import init_db, maintenance_lock, record_crawl, save_notice

STATIC_PAGES = [
    {"title": "졸업기준 안내", "category": "졸업", "url": "https://www.donga.ac.kr/kor/CMS/Contents/Contents.do?mCode=MN137"},
    {"title": "조기졸업 안내", "category": "졸업", "url": "https://www.donga.ac.kr/kor/CMS/Contents/Contents.do?mCode=MN140"},
]


def extract_static(soup):
    # Do not fall back to body/#contents, which also contain menus and page tools.
    node = first_node(soup, [".contents_view_wrap", ".content-detail", ".sub0101"])
    content = clean_text(node)
    if len(content) < 30:
        raise ValueError("정적 페이지 본문이 비어 있거나 너무 짧습니다")
    return content


def crawl_static():
    results = []
    fetcher = Fetcher()
    try:
        for page in STATIC_PAGES:
            try:
                soup = fetcher.fetch(page["url"])
                content = extract_static(soup)
                status = save_notice(source="동아대학교 학사안내", source_type="static", content=content, **page)
                from .attachments import register
                register(soup, page['url'])
                record_crawl(page["title"], status, page["url"])
                results.append({"title": page["title"], "status": status})
            except Exception as exc:
                record_crawl(page["title"], "failed", f"{type(exc).__name__}: {exc}")
                results.append({"title": page["title"], "status": "failed"})
    finally:
        fetcher.close()
    return results


if __name__ == "__main__":
    init_db()
    with maintenance_lock():
        print(crawl_static())
