"""Resumable source-by-source crawl. Supports Dong-A CMS; records all gaps."""
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import Column, DateTime, Integer, String, Text, select
from .crawl_common import clean_text, first_node
from .crawler import parse_listing, parse_detail
from .db import Base, digest, init_db, maintenance_lock, record_crawl, save_notice, session_scope, utcnow
from .public_catalog import CATALOG, PublicFetcher


class PublicSource(Base):
    __tablename__ = "public_sources"
    id = Column(String(64), primary_key=True)
    title = Column(String(1000), nullable=False)
    url = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)
    department = Column(String(100), nullable=False, default="")
    kind = Column(String(20), nullable=False)
    status = Column(String(40), nullable=False, default="pending")
    pages_scanned = Column(Integer, nullable=False, default=0)
    documents_saved = Column(Integer, nullable=False, default=0)
    last_attempt = Column(DateTime)
    message = Column(Text)


def register(catalog):
    with session_scope() as session:
        for source in catalog["sources"]:
            key = digest(source["department"] + "|" + source["url"])
            row = session.get(PublicSource, key)
            if row is None:
                row = PublicSource(id=key)
                session.add(row)
            for field in ("title", "url", "category", "department", "kind"):
                setattr(row, field, source[field])


def extract_static(soup):
    from .life_content import extract
    return extract(soup)


def crawl_one(source, fetcher, cutoff, max_pages):
    count, failed, pages = 0, 0, 0
    if source.kind == "review":
        return "adapter_required", 0, 0, "custom_page_or_external_service"
    if source.kind in {"static", "library"}:
        soup, _ = fetcher.fetch(source.url)
        from .life_content import extract
        save_notice(source=source.department or "동아대학교 공식홈페이지", source_type="static",
                    category=source.category, title=source.title, content=extract(soup, library=source.kind == 'library'),url=source.url)
        from .attachments import register
        register(soup, source.url)
        return "success", 1, 1, ""
    seen = set()
    finish = "page_limit"
    for page in range(1, max_pages + 1):
        try:
            soup, final = fetcher.fetch(source.url + f"&page={page}")
            items = parse_listing(soup, final)
        except Exception as exc:
            return "partial" if count else "failed", pages, count, f"page={page}; {type(exc).__name__}: {exc}"
        pages = page
        fresh = [i for i in items if i["url"] not in seen]
        if not fresh:
            finish = "repeated_page"
            break
        # Do not stop at an old pinned notice: visit the real pagination links.
        for item in fresh:
            seen.add(item["url"])
            if item["published_at"] and item["published_at"] < cutoff:
                continue
            try:
                detail, _ = fetcher.fetch(item["url"])
                parsed = parse_detail(detail,item)
                if parsed["published_at"] is None:
                    raise ValueError("missing_publication_date")
                if parsed["published_at"] < cutoff:
                    continue
                save_notice(source=source.department or source.title, source_type="notice",category=source.category,**parsed)
                from .attachments import register
                register(detail, item['url'])
                count += 1
            except Exception as exc:
                failed += 1
                record_crawl(source.title,"failed",f"{item['url']} {type(exc).__name__}: {exc}")
        # Date cutoff only for ordinary rows, with descending date evidence.
        ordinary=[]
        for row in soup.select("tr"):
            if row.select_one(".notice") or "isnotice" in row.get("class",[]):
                continue
            try:
                from bs4 import BeautifulSoup
                ordinary.extend(parse_listing(BeautifulSoup(str(row),"html.parser"),final))
            except ValueError:
                pass
        dates=[i["published_at"] for i in ordinary]
        if dates and all(d is not None for d in dates) and dates == sorted(dates,reverse=True) and max(dates) < cutoff:
            finish="date_boundary"
            break
        next_pages=[]
        for a in soup.select(".pagelist a[href], .bdListPaging a[href]"):
            q=parse_qs(urlsplit(a["href"]).query)
            if q.get("page",[""])[0].isdigit(): next_pages.append(int(q["page"][0]))
        if not next_pages or max(next_pages) <= page:
            finish="last_page"
            break
    state="partial" if failed or finish in {"page_limit","repeated_page"} else "success"
    return state,pages,count,f"stop={finish}; failed={failed}; cutoff={cutoff.date()}"


def run(catalog_path=CATALOG, days=365, max_pages=200, retry_only=False):
    catalog=json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    init_db()
    with maintenance_lock():
        register(catalog)
        with session_scope() as session:
            keys = [digest(s['department'] + '|' + s['url']) for s in catalog['sources']]
            query=select(PublicSource).where(PublicSource.id.in_(keys)).order_by(PublicSource.department.desc(),PublicSource.kind,PublicSource.url)
            if retry_only: query=query.where(PublicSource.status != "success")
            sources=list(session.scalars(query))
        fetcher=PublicFetcher()
        try:
            for source in sources:
                try:
                    status,pages,count,message=crawl_one(source,fetcher,datetime.now()-timedelta(days=days),max_pages)
                except Exception as exc:
                    status,pages,count,message="failed",0,0,f"{type(exc).__name__}: {exc}"
                with session_scope() as session:
                    row=session.get(PublicSource,source.id)
                    row.status=status; row.pages_scanned=pages; row.documents_saved=count
                    row.last_attempt=utcnow(); row.message=message[:4000]
                record_crawl(source.department or source.title,status,message)
                print(json.dumps({"source":source.title,"department":source.department,"status":status,"saved":count,"message":message},ensure_ascii=False),flush=True)
        finally:
            fetcher.close()


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--catalog",type=Path,default=CATALOG)
    parser.add_argument("--days",type=int,default=365)
    parser.add_argument("--max-pages",type=int,default=200)
    parser.add_argument("--retry-only",action="store_true")
    args=parser.parse_args()
    if not 1 <= args.days <= 3650 or not 1 <= args.max_pages <= 2000: parser.error("Invalid days/max-pages")
    run(args.catalog,args.days,args.max_pages,args.retry_only)
