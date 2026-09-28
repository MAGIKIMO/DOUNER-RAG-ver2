"""Compact verified exam rows before sending them to the language model."""
import re
from .document_context import as_document

def compact_exam_files(rows, question, budget=6000):
    grouped = {}
    normalize = lambda value: re.sub(r'\s+', '', value).lower()
    query = normalize(question)
    for row, page, attachment in rows:
        if '엑셀 시간표 행' not in row.content:
            continue
        grouped.setdefault(attachment.id, []).append((row, page, attachment))
    documents = []
    remaining = budget
    for group in list(grouped.values())[:2]:
        group.sort(key=lambda x: x[1].page_number)
        courses = [(item, re.search(r'(?m)^강의명: (.+)$', item[0].content)) for item in group]
        matching = [item for item, match in courses if match and normalize(match.group(1)) in query]
        chosen = matching or group
        lines = []
        for row, page, attachment in chosen:
            body = row.content.split('시험 시간표 · 시트:', 1)[-1]
            # Keep original field associations and room allocation continuation lines.
            fields = [line.strip() for line in body.splitlines()[1:] if line.strip() and '원문 미기재' not in line]
            row_number = re.search(r'엑셀 시간표 행 (\d+)', row.content).group(1)
            lines.append(f'[원본 행 {row_number}] ' + ' | '.join(fields))
        header = f'첨부파일: {group[0][2].filename}\n' + ('질문에 명시된 과목의 행만 발췌.\n' if matching else '수집된 시험 일정의 간결한 목록.\n')
        content = header
        included = 0
        for line in lines:
            if len(content) + len(line) + 120 > remaining:
                break
            content += line + '\n'; included += 1
        if not included:
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
