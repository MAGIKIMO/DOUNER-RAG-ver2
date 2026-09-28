"""Bounded PDF extraction worker. Scanned pages are explicitly marked unreadable."""
import io
import json
import sys

MAX_PAGES = 100
MAX_CHARS = 500000


def extract_pdf(blob):
    import pdfplumber
    if not blob.startswith(b'%PDF-'):
        raise ValueError('not_pdf')
    pages = []
    total = 0
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        if len(pdf.pages) > MAX_PAGES:
            raise ValueError('too_many_pages')
        for number, page in enumerate(pdf.pages, 1):
            text = page.extract_text(layout=True) or ''
            text = '\n'.join(line.rstrip() for line in text.splitlines()).strip()
            tables = []
            for index, table in enumerate(page.extract_tables(), 1):
                rows = [' | '.join((cell or '').replace('\n', ' / ').strip() for cell in row) for row in table]
                if rows:
                    tables.append(f'[표 {index}: 빈 셀은 원문 그대로이며 병합 관계를 추정하지 않음]\n' + '\n'.join(rows))
            # Keep layout text as well as row/cell representation for cross-checking.
            content = text + ('\n\n' + '\n\n'.join(tables) if tables else '')
            image_area = sum(max(0, img.get('x1', 0)-img.get('x0', 0)) * max(0, img.get('bottom', 0)-img.get('top', 0)) for img in page.images)
            large_image = image_area > page.width * page.height * 0.35
            readable = len(''.join(text.split())) >= 20 and '\ufffd' not in text and '(cid:' not in text and not large_image
            if not readable:
                content = ''
            total += len(content)
            if total > MAX_CHARS:
                raise ValueError('too_much_text')
            pages.append({'page': number, 'text': content, 'tables': len(tables),
                          'status': 'ok' if readable else 'ocr_or_review_required'})
            page.close()
    if not pages:
        raise ValueError('empty_pdf')
    return pages


if __name__ == '__main__':
    # stdin/stdout avoid persisted raw files and unsafe filename handling.
    try:
        if sys.platform == 'linux':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024, 1536 * 1024 * 1024))
            resource.setrlimit(resource.RLIMIT_CPU, (80, 80))
        result = extract_pdf(sys.stdin.buffer.read(20 * 1024 * 1024 + 1))
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    except Exception as exc:
        sys.stderr.write(type(exc).__name__ + ': ' + str(exc)[:200])
        sys.exit(1)
