"""Compact verified exam rows before sending them to the language model."""
import re
from .document_context import as_document
from .exam_records import decode, select as select_records, formatted, course_matches

def compact_exam_files(rows, question, budget=6000):
    grouped = {}
    normalize = lambda value: re.sub(r'\s+', '', value).lower()
    query = normalize(question)
    for row, page, attachment in rows:
        grouped.setdefault(attachment.id, []).append((row, page, attachment))
    documents = []
    remaining = budget
    def course_hits(group):
        return sum(bool(m and normalize(m[1]) in query) for row, _, _ in group
                   for m in [re.search(r'(?m)^강의명: (.+)$', row.content)]) + sum(course_matches(r['course'],question) for row,_,_ in group for r in decode(row.content))
    # Prefer the file containing the asked-for course, even if other attachments
    # were registered first. Keep the existing two-file token bound.
    groups = sorted(grouped.values(), key=lambda group:(course_hits(group),sum(r['time_basis']=='explicit' for row,_,_ in group for r in decode(row.content))), reverse=True)
    for group in groups[:2]:
        group.sort(key=lambda x: x[1].page_number)
        normalized = [r for row,_,_ in group for r in decode(row.content)]
        courses = [(item, re.search(r'(?m)^강의명: (.+)$', item[0].content)) for item in group]
        matching = [item for item, match in courses if match and normalize(match.group(1)) in query]
        chosen = matching or group
        section_missing = False
        sections = re.findall(r'(\d{1,3})\s*분반', question)
        if matching and sections:
            requested = int(sections[-1])
            filtered = []
            for item in matching:
                section = re.search(r'(?m)^분반 or 합반:\s*(.+)$', item[0].content)
                if not section:
                    continue
                value = section[1].strip()
                # Only interpret explicit section numbers, never year-of-study
                # digits or classroom numbers. Combined classes remain explicit.
                numbers = re.findall(r'(?<!\d)(\d{1,3})\s*분반', value)
                if re.fullmatch(r'\d{1,3}', value): numbers = [value]
                if '합반' in value and not re.search(r'\d', value):
                    filtered.append(item)
                elif requested in [int(n) for n in numbers]:
                    filtered.append(item)
            chosen = filtered
            section_missing = not filtered
        lines = []
        if normalized:
            selected, matched = select_records(normalized,question)
            lines=formatted(selected)
            matching=matched
            section_missing=matched and not selected
            chosen=[]
        for row, page, attachment in chosen:
            if '엑셀 시간표 행' not in row.content:
                from .exam_pdf import formatted_lines
                structured = formatted_lines(row.content, question)
                if structured:
                    lines.extend(structured)
                    continue
                lines.append(f'[원본 {page.page_number}쪽] ' + row.content)
                continue
            body = row.content.split('시험 시간표 · 시트:', 1)[-1]
            # Keep original field associations and room allocation continuation lines.
            fields = [line.strip() for line in body.splitlines()[1:] if line.strip() and '원문 미기재' not in line]
            row_number = re.search(r'엑셀 시간표 행 (\d+)', row.content).group(1)
            lines.append(f'[원본 행 {row_number}] ' + ' | '.join(fields))
        header = f'첨부파일: {group[0][2].filename}\n' + ('질문에 명시된 과목의 행만 발췌.\n' if matching else '수집된 시험 일정의 간결한 목록.\n')
        if section_missing:
            header += ('[요청한 과목은 있으나 요청 분반과 일치하는 행은 이 파일의 추출 자료에서 확인되지 않음. '
                       '다른 분반 시간으로 대신 답하지 말고 분반 정보를 확인하세요.]\n')
        if normalized:
            header += '[원문 위치가 있는 구조화 일정만 발췌. 미인식 행이 있을 수 있으며 서로 다른 강의실을 임의로 하나로 확정하지 마세요.]\n'
            if any(r['time_basis']=='grid' for r in normalized):
                header += '[격자 배치 범위는 세부 분 단위 시험 시각과 다를 수 있습니다. 별도 상세표에 명시된 시각이 있으면 그 근거를 밝히고 답하세요. 해결되지 않는 충돌은 함께 알리세요.]\n'
        content = header
        included = 0
        for line in lines:
            if len(content) + len(line) + 120 > remaining:
                if not included and remaining - len(content) > 200:
                    content += line[:remaining - len(content) - 120] + '\n[해당 페이지 일부 발췌]'
                    included += 1
                break
            content += line + '\n'; included += 1
        if not included and not section_missing:
            continue
        if len(content) > remaining:
            continue
        if included < len(lines):
            content += '\n[일부 행 생략: 전체 시간표라고 단정하지 말고 과목·학년·분반을 확인하세요.]'
        if group[0][2].status == 'partial':
            content += '\n[추출되지 않은 부분이 있는 첨부파일입니다.]'
        row, page, attachment = group[0]
        doc = as_document(row)
        doc.title = attachment.filename
        doc.chunk_text = content
        doc.url = attachment.url
        doc.attachment = {'filename': attachment.filename, 'checked_at': attachment.checked_at.isoformat()+'Z' if attachment.checked_at else None}
        documents.append(doc)
        remaining -= len(content)
    return documents
