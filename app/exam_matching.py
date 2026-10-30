"""Shared, semester-scoped exam matching across departments."""
import re
EXAM = re.compile(r'(중간|기말)\s*(?:고사|시험)')

def matches(title, content, published_at, year, term, kind):
    if not re.search(('기말' if '기말' in kind else '중간') + r'\s*(?:고사|시험)', title):
        return False
    compact = re.search(r'(20\d{2})\s*[-–/]\s*([12])(?:\D|$)', title)
    years = re.findall(r'(?<!\d)(20\d{2})(?!\d)', title)
    terms = re.findall(r'([12])\s*학기', title)
    if compact:
        years, terms = [compact[1]], [compact[2]]
    if years and str(year) not in years:
        return False
    if terms and str(term) not in terms:
        return False
    if not years:
        body_years = re.findall(r'(20\d{2})\s*(?:학년도|년도|년)', content)
        if body_years:
            if str(year) not in body_years: return False
        elif not published_at or published_at.year != int(year): return False
    if not terms:
        body_terms = re.findall(r'([12])\s*학기', content)
        if body_terms:
            if str(term) not in body_terms: return False
        elif not published_at or ('1' if published_at.month < 8 else '2') != str(term): return False
    return True
