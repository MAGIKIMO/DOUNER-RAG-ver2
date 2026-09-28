from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from .config import integer
from .crawl_common import Fetcher, clean_text, first_node, parse_date
from .db import init_db, maintenance_lock, record_crawl, save_notice

# Current menu URLs verified 2026-09-14. Original MN122/123/124 are not these boards.
BOARDS = [
    ("동아대학교 일반공지", "일반공지", "https://www.donga.ac.kr/kor/CMS/Board/Board.do?mCode=MN170"),
    ("동아대학교 학사공지", "학사공지", "https://www.donga.ac.kr/kor/CMS/Board/Board.do?mCode=MN171"),
    ("동아대학교 장학공지", "장학공지", "https://www.donga.ac.kr/kor/CMS/Board/Board.do?mCode=MN172"),
    ("국제교류처 공지", "국제교류", "https://global.donga.ac.kr/global/CMS/Board/Board.do?mCode=MN066"),
    ("컴퓨터공학과 공지", "컴퓨터공학과", "https://computer.donga.ac.kr/computer/CMS/Board/Board.do?mCode=MN044"),
]


def parse_listing(soup, base_url):
    items = {}
    for anchor in soup.select("td.subject a[href], .stitle a[href]"):
        url = urljoin(base_url, anchor["href"])
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if parts.netloc != urlsplit(base_url).netloc or query.get("mode") != ["view"] or not query.get("board_seq"):
            continue
        canonical = {key: query[key][0] for key in ("mCode", "mode", "mgr_seq", "board_seq") if key in query}
        url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(canonical), ""))
        row = anchor.find_parent("tr")
        date = row.select_one(".date") if row else None
        items[url] = {"url": url, "title": clean_text(anchor), "published_at": parse_date(date.get_text() if date else "")}
    if not items:
        raise ValueError("게시글 링크가 없습니다. 주소/선택자/접근 제한을 확인하세요.")
    return list(items.values())


def parse_detail(soup, item):
    title_node = first_node(soup, [".bdViewTit .viewTit", ".bdViewTit", ".board-view-title"])
    title = clean_text(title_node).replace("\n", " ").strip()
    content = clean_text(first_node(soup, ["#boardContents", ".board-view-content"]))
    from .attachments import discover
    if title and len(content) < 20 and discover(soup, item['url']):
        content = (content + '\n첨부파일 안내 공지입니다. 첨부파일의 내용은 별도 추출이 필요합니다.').strip()
    if not title or len(content) < 20:
        raise ValueError("공지 본문이 부족합니다. 이미지/첨부파일 전용 공지는 MVP 수집 대상에서 제외됩니다.")
    date = soup.select_one(".viewTitWinfo .date")
    return {"url": item["url"], "title": title, "content": content,
            "published_at": parse_date(date.get_text()) if date else item["published_at"]}


def crawl_notices():
    results = []
    fetcher = Fetcher()
    try:
        for source, category, base_url in BOARDS:
            seen = set()
            counts = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
            candidates = {}
            for page in range(1, integer("CRAWL_PAGES", 1, maximum=10) + 1):
                try:
                    for item in parse_listing(fetcher.fetch(base_url + f"&page={page}"), base_url):
                        candidates[item["url"]] = item
                except Exception as exc:
                    counts["failed"] += 1
                    record_crawl(source, "failed", f"page={page} {type(exc).__name__}: {exc}")
            # Pinned posts must not consume the entire recent-notice budget.
            ordered = sorted(candidates.values(), key=lambda item: str(item["published_at"] or ""), reverse=True)
            for item in ordered[:integer("CRAWL_MAX_NOTICES", 10, maximum=100)]:
                if item["url"] in seen:
                    continue
                seen.add(item["url"])
                try:
                    detail = fetcher.fetch(item["url"])
                    parsed = parse_detail(detail, item)
                    status = save_notice(source=source, source_type="notice", category=category, **parsed)
                    from .attachments import register
                    register(detail, item['url'])
                    counts[status] += 1
                except Exception as exc:
                    counts["failed"] += 1
                    record_crawl(source, "failed", f"{item['url']} {type(exc).__name__}: {exc}")
            record_crawl(source, "partial" if counts["failed"] else "success", str(counts))
            results.append({"source": source, **counts})
    finally:
        fetcher.close()
    return results


if __name__ == "__main__":
    init_db()
    with maintenance_lock():
        print(crawl_notices())
