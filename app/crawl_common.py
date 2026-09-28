import os
import re
import time
from datetime import datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

NOISE = re.compile(r"스킵\s*네비게이션|본문\s*바로가기|주메뉴\s*바로가기|SNS\s*공유|url\s*복사", re.I)


def clean_text(value):
    soup = BeautifulSoup(str(value), "html.parser")
    for node in soup.select("script, style, nav, header, footer, noscript, button, .allim-box, .blind, .sns, .skip, .bdViewFiles"):
        node.decompose()
    # Preserve table rows and cell separators; avoid joining unrelated cells.
    for row in soup.select("tr"):
        row.replace_with("\n" + " | ".join(cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"], recursive=False)) + "\n")
    lines = []
    for line in soup.get_text("\n", strip=True).splitlines():
        line = re.sub(r"\s+", " ", NOISE.sub("", line)).strip()
        if line and line not in {"인쇄", "공유", "목록", "이전글", "다음글"}:
            lines.append(line)
    return "\n".join(lines)


def parse_date(value):
    match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", value or "")
    if not match:
        return None
    try:
        return datetime(*map(int, match.groups()))
    except ValueError:
        return None


def first_node(soup, selectors):
    for selector in selectors:
        node = soup.select_one(selector)
        if node is not None:
            return node
    raise ValueError("본문 선택자를 찾지 못했습니다. 학교 페이지 구조를 확인하세요.")


class Fetcher:
    def __init__(self):
        self.agent = os.getenv("CRAWLER_USER_AGENT", "DongaRAGStudentProject/2.0")
        self.client = httpx.Client(timeout=20, follow_redirects=False, headers={"User-Agent": self.agent})
        self.robots = {}
        self.last_request = 0.0

    def close(self):
        self.client.close()

    def _get(self, url):
        delay = max(0.5, float(os.getenv("CRAWL_DELAY_SECONDS", "1")))
        time.sleep(max(0, delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        return self.client.get(url)

    def fetch(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.donga.ac.kr", "global.donga.ac.kr", "computer.donga.ac.kr"}:
            raise ValueError("허용되지 않은 수집 주소")
        origin = f"https://{parsed.netloc}"
        if origin not in self.robots:
            response = self._get(origin + "/robots.txt")
            if response.status_code == 404:
                lines = []
            else:
                response.raise_for_status()
                lines = response.text.splitlines()
            robot = RobotFileParser()
            robot.parse(lines)
            self.robots[origin] = robot
        if not self.robots[origin].can_fetch(self.agent, url):
            raise ValueError("robots.txt에서 수집을 허용하지 않습니다")
        response = self._get(url)
        response.raise_for_status()
        if "html" not in response.headers.get("content-type", "").lower():
            raise ValueError("HTML 응답이 아닙니다")
        return BeautifulSoup(response.content, "html.parser", from_encoding="utf-8")
