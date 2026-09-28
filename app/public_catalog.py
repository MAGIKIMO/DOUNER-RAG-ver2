"""Discover public official menu pages and departments; never guess missing URLs."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from .crawl_common import Fetcher

MAIN = "https://www.donga.ac.kr/kor/Main.do"
COLLEGES = "https://www.donga.ac.kr/kor/CMS/Contents/Contents.do?mCode=MN272"
CATALOG = Path(__file__).with_name("public_sources.json")
BLOCKED = {"eclass.donga.ac.kr", "lms.donga.ac.kr", "dx.donga.ac.kr", "portal.donga.ac.kr", "dxsugang.donga.ac.kr"}


def public_url(url):
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    return (p.scheme == "https" and not p.username and p.port in {None, 443}
            and (host == "donga.ac.kr" or host.endswith(".donga.ac.kr"))
            and host not in BLOCKED and not re.search(r"login|logout|member|sso|download|delete|write|modify", p.path, re.I))


def canonical(url):
    p = urlsplit(url)
    q = parse_qs(p.query)
    keep = {k: q[k][0] for k in ("mCode", "mgr_seq", "dept_cd") if k in q}
    return urlunsplit(("https", p.netloc.lower(), p.path or "/", urlencode(keep), ""))


class PublicFetcher(Fetcher):
    def fetch(self, url):
        from urllib.robotparser import RobotFileParser
        for _ in range(6):
            if not public_url(url):
                raise ValueError("not_public_official_url")
            p = urlsplit(url)
            origin = f"https://{p.netloc}"
            if origin not in self.robots:
                r = self._get(origin + "/robots.txt")
                if r.status_code == 404:
                    lines = []
                else:
                    r.raise_for_status()
                    if "<html" in r.text[:1000].lower():
                        raise ValueError("robots_response_is_html")
                    lines = r.text.splitlines()
                robot = RobotFileParser()
                robot.parse(lines)
                self.robots[origin] = robot
            if not self.robots[origin].can_fetch(self.agent, url):
                raise ValueError("robots_disallowed")
            r = self._get(url)
            if r.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            if "html" not in r.headers.get("content-type", "").lower():
                raise ValueError("not_html")
            return BeautifulSoup(r.content, "html.parser", from_encoding="utf-8"), url
        raise ValueError("too_many_redirects")


def classify(url):
    p = urlsplit(url)
    if "/CMS/Contents/Contents.do" in p.path:
        return "static"
    if "/CMS/Board/Board.do" in p.path:
        return "board"
    return "review"


def menu_entries(soup, base, department=""):
    found = {}
    for a in soup.select("a[href]"):
        label = a.get_text(" ", strip=True)
        href = a.get("href", "").strip()
        if not label or not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = canonical(urljoin(base, href))
        if not public_url(url):
            continue
        kind = classify(url)
        if department and kind == "board" and not re.search(r"공지|학사|장학|notice", label, re.I):
            continue
        if department and urlsplit(url).hostname != urlsplit(base).hostname:
            continue
        if department and urlsplit(base).path.strip("/"):
            site_prefix = urlsplit(base).path.strip("/").split("/")[0]
            if not urlsplit(url).path.startswith("/" + site_prefix + "/"):
                continue
        parent = a.find_parent("li", class_=re.compile(r"mn_li1"))
        heading = parent.select_one("a.mn_a1") if parent else None
        category = department or (heading.get_text(" ", strip=True) if heading else "학교 공통")
        if kind in {"static", "board"} and not parse_qs(urlsplit(url).query).get("mCode"):
            continue
        found.setdefault(url, {"url":url, "title":label, "category":category,
                              "department":department, "kind":kind, "discovered_from":base})
    return list(found.values())


def discover(output=CATALOG):
    fetcher = PublicFetcher()
    result = {"discovered_at": datetime.now(timezone.utc).isoformat(), "sources":[], "departments":[], "failures":[]}
    try:
        home, final = fetcher.fetch(MAIN)
        result["sources"].extend(menu_entries(home, final))
        college, final = fetcher.fetch(COLLEGES)
        for unit in college.select(".deptSummUnit"):
            name = unit.select_one(".role-head .t1")
            anchor = unit.select_one(".role-head a.btnSite[href]")
            if name is None:
                continue
            department = name.get_text(" ", strip=True)
            entry = {"name":department, "url":canonical(urljoin(final,anchor["href"])) if anchor and anchor["href"].strip() else "", "status":"pending"}
            result["departments"].append(entry)
            if not entry["url"] or not public_url(entry["url"]):
                entry["status"] = "missing_or_external_homepage"
                continue
            try:
                page, resolved = fetcher.fetch(entry["url"])
                sources = menu_entries(page, resolved, department)
                result["sources"].extend(sources)
                entry["status"] = "board_discovered" if any(s["kind"] == "board" for s in sources) else "board_adapter_required"
            except Exception as exc:
                entry["status"] = "failed"
                entry["error"] = type(exc).__name__ + ": " + str(exc)[:300]
            print(json.dumps(entry,ensure_ascii=False), flush=True)
            Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    finally:
        fetcher.close()
        # Same board may appear in several menus; preserve department ownership.
        result["sources"] = list({(s["department"],s["url"]):s for s in result["sources"]}.values())
        Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/donga-public-sources.json"))
    args = parser.parse_args()
    discover(args.output)
