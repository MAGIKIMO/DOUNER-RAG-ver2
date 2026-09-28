from bs4 import BeautifulSoup
import pytest
from app.life_content import extract


def test_calendar_pairs_dates_with_events():
    soup=BeautifulSoup('<div class="contents_view_wrap"><h3>2026 academic calendar</h3><table><tr><td>Fall</td><td><ul><li>2026-09-01</li><li></li><li>2026-12-12</li></ul></td><td><ul><li>Start</li><li></li><li>Final exams</li></ul></td></tr></table></div>','html.parser')
    soup.table.insert(0, BeautifulSoup('<thead><tr><th>학기</th><th>기간</th><th>업무</th></tr></thead>', 'html.parser'))
    text=extract(soup)
    assert 'Fall | 2026-09-01 | Start' in text
    assert 'Fall | 2026-12-12 | Final exams' in text


def test_calendar_mismatch_rejected():
    soup=BeautifulSoup('<div id="cont"><table><tr><td><ul><li>A</li><li>B</li></ul></td><td><ul><li>Only one</li></ul></td></tr></table></div>','html.parser')
    soup.table.insert(0, BeautifulSoup('<thead><tr><th>기간</th><th>업무</th></tr></thead>', 'html.parser'))
    with pytest.raises(ValueError, match='unaligned'):
        extract(soup)


def test_library_merged_cells_and_menu_exclusion():
    soup=BeautifulSoup('<nav>Secret unrelated navigation</nav><div class="contents-body"><h3>Library opening hours</h3><table><tr><th>Room</th><th colspan="2">Weekdays</th></tr><tr><td>A</td><td rowspan="2">09:00</td><td>20:00</td></tr><tr><td>B</td><td>17:00</td></tr></table></div>','html.parser')
    text=extract(soup,library=True)
    assert 'B | 09:00 | 17:00' in text
    assert 'Secret' not in text


def test_image_only_does_not_become_evidence():
    with pytest.raises(ValueError,match='image_only'):
        extract(BeautifulSoup('<div class="contents-body"><img src="poster.png"></div>','html.parser'),library=True)
