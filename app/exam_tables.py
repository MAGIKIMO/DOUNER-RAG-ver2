"""Recognize explicit row tables; only the caller may restore real merged cells."""
import re
from .exam_records import validate

ALIASES = {
    'course': ('강의명','과목명','교과목명'),
    'date': ('요일','날짜','시험일자','시험일'),
    'start': ('시험시작시간','시작시간','시작'),
    'end': ('시험종료시간','종료시간','종료'),
    'time': ('시간','시험시간'),
    'datetime': ('시험일시(시간)','시험일시'),
    'section': ('분반','분반or합반','학과/분반'),
    'room': ('강의실','강의실1','시험장소','장소','강의실(분반)'),
    'professor': ('교수','교수명','교수님','담당교수'),
    'notes': ('비고','오픈북여부'),
}
TIME = re.compile(r'(\d{1,2}:\d{2})\s*[~～–−-]\s*(\d{1,2}:\d{2})')
DATE = re.compile(r'(?<![\d:])(?:(20\d{2})[./-])?(\d{1,2})[./월-]\s*(\d{1,2})(?![\d:])(?:일)?(?:\.?\s*\([월화수목금토일](?:요일)?\))?')


def label(value):
    value = re.sub(r'\s+', '', value)
    return next((key for key, aliases in ALIASES.items() if value in aliases), None)


def clock(value):
    if re.fullmatch(r'0?\.\d+', value):
        minutes = round(float(value)*24*60)
        return f'{minutes//60:02d}:{minutes%60:02d}'
    return value.strip()


def records(matrix, location):
    headers = None
    output = []
    for number, values in matrix:
        labels = {index:label(v) for index,v in enumerate(values) if label(v)}
        fields = set(labels.values())
        if 'course' in fields and ('datetime' in fields or ('date' in fields and ('time' in fields or {'start','end'} <= fields))):
            headers = labels
            continue
        if headers is None:
            continue
        row = {key:values[index].strip() for index,key in headers.items() if index < len(values)}
        if not row.get('course'):
            continue
        when = row.get('datetime',row.get('date',''))
        dates = list(DATE.finditer(when))
        if len(dates)!=1:
            continue
        d = dates[0]
        row['date']=(d[1]+'-' if d[1] else '')+d[2]+'-'+d[3]
        if 'time' in row or 'datetime' in row:
            times = list(TIME.finditer(row.get('datetime',row.get('time',''))))
            if len(times)!=1:
                continue  # Never pair multiple dates/rooms by positional guessing.
            row['start'],row['end'] = times[0].groups()
        else:
            row['start'],row['end'] = clock(row.get('start','')),clock(row.get('end',''))
        row.update(time_basis='explicit',location=f'{location} · 행 {number}')
        valid = validate(row)
        if valid:
            output.append(valid)
    return output


def pdf_matrix(table):
    """Recover None cells only if a real PDF cell bounding box spans their center."""
    extracted = table.extract()
    cells = [c for c in table.cells if c]
    tops = sorted(set(c[1] for c in cells))
    lefts = sorted(set(c[0] for c in cells))
    if len(tops)!=len(extracted) or not cells:
        return [(i+1, [v or '' for v in row]) for i,row in enumerate(extracted)]
    owners = {}
    for row,geometry in zip(extracted,table.rows):
        for value,box in zip(row,geometry.cells):
            if box and value is not None:
                owners[tuple(box)] = value
    output=[]
    for ri,row in enumerate(extracted):
        bottom = tops[ri+1] if ri+1<len(tops) else max(c[3] for c in cells)
        values=[]
        for ci,value in enumerate(row):
            if value is None and ci<len(lefts):
                right = lefts[ci+1] if ci+1<len(lefts) else max(c[2] for c in cells)
                x,y=(lefts[ci]+right)/2,(tops[ri]+bottom)/2
                spans=[box for box in owners if box[0]<x<box[2] and box[1]<y<box[3]]
                if len(spans)==1:
                    value=owners[spans[0]]
            values.append(value or '')
        output.append((ri+1,values))
    return output
