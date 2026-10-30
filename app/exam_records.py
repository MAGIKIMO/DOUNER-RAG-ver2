"""Common, source-located exam records. Validation never supplies missing facts."""
import json
import re
import unicodedata
from datetime import date

MARKER = '시험일정JSON: '
FIELDS = ('course', 'date', 'start', 'end', 'section', 'room', 'professor', 'notes', 'time_basis', 'location')


def normalize(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value)).casefold()


def course_matches(course, question):
    name, query = normalize(course), normalize(question)
    if re.search(re.escape(name)+r'(?![ivx])',query):
        return True
    base=re.sub(r'[ivx]+$','',name)
    return base!=name and len(base)>=3 and bool(re.search(re.escape(base)+r'(?![ivx])',query))


def validate(record):
    if not isinstance(record, dict):
        return None
    row = {key:re.sub(r'[\r\n|]+', ' ', str(record.get(key) or '')).strip()[:500] for key in FIELDS}
    if not row['course'] or len(row['course']) > 150:
        return None
    match = re.fullmatch(r'(?:(20\d{2})[./-])?(\d{1,2})[./-](\d{1,2})(?:\.?\s*\([월화수목금토일](?:요일)?\))?', row['date'])
    if not match:
        return None
    try:
        date(int(match[1] or 2000), int(match[2]), int(match[3]))
    except ValueError:
        return None
    row['date'] = (match[1]+'-' if match[1] else '')+f'{int(match[2]):02d}-{int(match[3]):02d}'
    for key in ('start', 'end'):
        m = re.fullmatch(r'(\d{1,2}):(\d{2})', row[key])
        if not m or int(m[1])>23 or int(m[2])>59:
            return None
        row[key] = f'{int(m[1]):02d}:{int(m[2]):02d}'
    if row['start'] >= row['end']:
        return None
    basis={'explicit':'explicit','printed':'explicit','grid':'grid','grid_derived':'grid','grid-derived':'grid'}
    if row['time_basis'] not in basis: return None
    row['time_basis']=basis[row['time_basis']]
    return row


def encode(rows):
    return '\n'.join(MARKER+json.dumps(row, ensure_ascii=False, separators=(',',':')) for row in rows)


def decode(text):
    rows = []
    for line in text.splitlines():
        if not line.startswith(MARKER):
            continue
        try:
            row = validate(json.loads(line[len(MARKER):]))
        except (ValueError, TypeError):
            continue
        if row and row not in rows:
            rows.append(row)
    return rows


def select(rows, question):
    query = normalize(question)
    matched = [r for r in rows if course_matches(r['course'],question)]
    if not matched:
        return rows, False
    sections = re.findall(r'(\d{1,3})\s*분반', question)
    if sections:
        requested = int(sections[-1])
        matched = [r for r in matched if requested in [int(n) for n in re.findall(r'\d{1,3}',r['section'])]]
    return matched, True


def formatted(rows):
    return [f"[정규화 일정 {i}] 강의명: {r['course']} | 시험일: {r['date']} | 시간: {r['start']}~{r['end']} | 분반: {r['section'] or '미기재'} | 강의실: {r['room'] or '미기재'} | 교수: {r['professor'] or '미기재'} | 안내: {r['notes']} | 시간 근거: {'격자 배치 범위(세부 시각 표와 다를 수 있음)' if r['time_basis']=='grid' else '원문 명시 시각'} | 원문 위치: {r['location']}" for i,r in enumerate(rows,1)]
