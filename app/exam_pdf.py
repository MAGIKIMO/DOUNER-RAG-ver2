"""Read explicit weekday/date columns from extracted PDF tables, never layout text."""
import re

TIME = re.compile(r'^(\d{1,2}:\d{2})\s*[~～–-]\s*(\d{1,2}:\d{2})$')

def schedules(content):
    records = []
    for block in re.split(r'\[표 \d+:[^\]]*\]\n', content)[1:]:
        rows = [[cell.strip() for cell in line.split('|')] for line in block.splitlines() if '|' in line]
        for index, header in enumerate(rows):
            columns = {i:value for i,value in enumerate(header) if re.fullmatch('[월화수목금토일](?:요일)?',value)}
            if len(columns) < 3 or index+1 >= len(rows): continue
            date_row = rows[index+1]
            # Blank header cells may be subcolumns, but only if between explicit
            # weekday boundaries. Do not infer dates for unknown subcolumns.
            for column, weekday in columns.items():
                if column >= len(date_row) or not re.fullmatch(r'(?:\d{1,2}[./월]\s*)?\d{1,2}일?',date_row[column]): continue
                accumulated = []
                def finish():
                    if not accumulated: return
                    parts = [p.strip() for cell in accumulated for p in cell.split('/') if p.strip()]
                    time = TIME.fullmatch(parts[0])
                    if not time: return
                    if any(not (0 <= int(t.split(':')[0]) < 24 and 0 <= int(t.split(':')[1]) < 60) for t in time.groups()): return
                    section_index = next((i for i,p in enumerate(parts[1:],1) if re.fullmatch(r'[\d,\s]+분반',p)),None)
                    if section_index is None or section_index < 2: return
                    course = ' '.join(parts[1:section_index])
                    if len(course)>100 or TIME.search(course): return
                    tail = parts[section_index+1:]
                    record = {'course':course, 'date':date_row[column]+'('+weekday+')',
                              'time':parts[0], 'section':parts[section_index], 'details':' / '.join(tail)}
                    if record not in records: records.append(record)
                for row in rows[index+2:]:
                    cell = row[column] if column < len(row) else ''
                    if not cell: continue
                    first = cell.split('/')[0].strip()
                    if TIME.fullmatch(first):
                        finish(); accumulated = [cell]
                    elif accumulated:
                        accumulated.append(cell)
                finish()
            break
    return sorted(records, key=lambda r:(tuple(int(n) for n in re.findall(r'\d+',r['date'])),r['time']))

def formatted_lines(content, question):
    rows = schedules(content)
    normalize = lambda s: re.sub(r'\s+', '', s)
    matches = [row for row in rows if normalize(row['course']) in normalize(question)]
    selected = matches or rows
    sections = re.findall(r'(\d+)\s*분반', question)
    if sections and matches:
        selected = [row for row in matches if int(sections[-1]) in [int(n) for n in re.findall(r'\d+',row['section'])]]
        if not selected:
            return ['[요청한 과목의 해당 분반을 추출된 표에서 확인하지 못함. 다른 분반으로 대신 답하지 마세요.]']
    return [f"[PDF 일정 {i}] 강의명: {r['course']} | 시험일: {r['date']} | 시간: {r['time']} | 분반: {r['section']} | 안내: {r['details']}"
            for i,r in enumerate(selected,1)] + (['[표에서 인식한 일정만 발췌: 전체 시간표가 아니며 인식하지 못한 병합 셀이 있을 수 있음]'] if selected else [])
