import json
from types import SimpleNamespace
import httpx
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select, func
from sqlalchemy.pool import StaticPool
from app import db, attachments, rag_service
from app.document_context import as_document, with_attachments
from app.ingest_notices_to_context import ingest_chunks
from app.crawler import parse_detail

URL = 'https://www.donga.ac.kr/notice'
FILE = 'https://www.donga.ac.kr/download.pdf'


@pytest.fixture(autouse=True)
def database(monkeypatch):
    engine = create_engine('sqlite://', poolclass=StaticPool)
    monkeypatch.setattr(db, 'engine', lambda: engine)
    db.init_db()
    yield
    engine.dispose()


def parent(url=URL, category='테스트'):
    db.save_notice(source='테스트', source_type='notice', category=category,
                   title='테스트 장학 신청 안내', content='자세한 제출서류는 첨부파일을 확인하세요.', url=url)
    soup = BeautifulSoup(f'<div class="bdViewFiles"><a href="{FILE}">신청안내.pdf</a></div>', 'html.parser')
    attachments.register(soup, url)
    with db.session_scope() as session:
        row = session.scalar(select(db.Notice).where(db.Notice.url == url))
        item = session.scalar(select(db.Attachment).where(db.Attachment.parent_id == row.id))
    return row, item, soup


def pages(text='제출서류는 신청서와 재학증명서입니다. 학생 본인이 제출합니다.'):
    return [{'page': 1, 'text': text, 'tables': 0, 'status': 'ok'}]


def test_discovers_download_endpoint_and_rejects_external_and_script():
    soup = BeautifulSoup('<div id="boardContents"><a href="/kor/ajx_json/UploadMgr/downloadRun.do?qcode=123">문서.pdf</a><a href="https://evil.example/a.pdf">외부.pdf</a><a href="javascript:download()">문서.pdf</a></div>', 'html.parser')
    links = attachments.discover(soup, URL)
    assert len(links) == 1
    assert 'qcode=123' in next(iter(links))
    for value in ['https://www.donga.ac.kr.evil.example/a.pdf', 'http://www.donga.ac.kr/a.pdf', 'https://eclass.donga.ac.kr/a.pdf', 'https://user@www.donga.ac.kr/a.pdf', 'https://www.donga.ac.kr:999/a.pdf']:
        assert not attachments.file_url(value)


def test_attachment_only_notice_is_saved_for_later_extraction():
    soup = BeautifulSoup(f'<div class="bdViewTit">신청 안내</div><div id="boardContents">첨부 참조</div><div class="bdViewFiles"><a href="{FILE}">문서.pdf</a></div>', 'html.parser')
    assert '별도 추출' in parse_detail(soup, {'url': URL, 'published_at': None})['content']


def test_page_update_removal_and_category_ownership():
    row, item, _ = parent()
    attachments.save_pages(item.id, 'first', pages()+[{'page': 2, 'text': '두 번째 페이지 내용입니다.', 'status': 'ok'}])
    ingest_chunks()
    attachments.save_pages(item.id, 'second', pages('수정된 제출서류 내용입니다. 신청서를 제출하세요.'))
    with db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(db.AttachmentPage)) == 1
        doc = session.scalar(select(db.Notice).where(db.Notice.source_type == 'attachment'))
        assert doc.category == row.category and '수정된' in doc.content
    assert ingest_chunks()['changed_documents'] == 1
    attachments.register(BeautifulSoup('<div id="boardContents">파일 삭제됨</div>', 'html.parser'), URL)
    with db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(db.AttachmentPage)) == 0
        assert session.get(db.Attachment, item.id).status == 'removed'


def test_unchanged_binary_skips_extraction_and_parent_change_refreshes(monkeypatch):
    row, item, _ = parent()
    calls = []
    monkeypatch.setattr(attachments, 'extract', lambda blob: calls.append(blob) or pages())
    fetcher = SimpleNamespace(download=lambda url: b'%PDF-test')
    assert attachments.process(item.id, fetcher) == 'extracted'
    assert attachments.process(item.id, fetcher) == 'unchanged'
    assert len(calls) == 1
    with db.session_scope() as session:
        original = session.get(db.Notice, row.id); original.content_hash = 'changed'; original.category = '다른 분류'
    assert attachments.process(item.id, fetcher) == 'extracted'
    with db.session_scope() as session:
        assert session.scalar(select(db.Notice.category).where(db.Notice.source_type == 'attachment')) == '다른 분류'


def test_failed_or_unsupported_file_is_visible_and_not_used_as_current_evidence():
    row, item, _ = parent()
    attachments.save_pages(item.id, 'hash', pages())
    assert attachments.process(item.id, SimpleNamespace(download=lambda url: b'<html>login</html>')) == 'failed'
    docs = with_attachments([as_document(row)], '제출서류')
    assert len(docs) == 1
    with db.session_scope() as session:
        assert session.get(db.Attachment, item.id).status == 'failed'
    attachments.process(item.id, SimpleNamespace(download=lambda url: b'\xd0\xcf\x11\xe0hwp'))
    with db.session_scope() as session:
        assert session.get(db.Attachment, item.id).status == 'unsupported'


def test_parent_hit_supplies_attachment_to_llm_and_returns_page_citation(monkeypatch):
    row, item, _ = parent()
    attachments.save_pages(item.id, 'hash', pages())
    def generate(system, user):
        docs = json.loads(user)['documents']
        found = next(d for d in docs if '재학증명서' in d['text'])
        assert 'PDF 1쪽' in found['text']
        return f'신청서와 재학증명서가 필요합니다. [{found["source"]}]'
    monkeypatch.setattr(rag_service, 'generate_answer', generate)
    result = rag_service.compose_answer('필요한 서류가 뭐야?', [as_document(row)], 'ko', {})
    assert '재학증명서' in result['answer']
    source = next(s for s in result['sources'] if s['source_type'] == 'attachment')
    assert source['attachment']['page'] == 1 and source['attachment']['parent_url'] == URL
    assert source['url'] == FILE+'#page=1'


def test_partial_pdf_exposes_only_readable_pages_and_warning():
    row, item, _ = parent()
    attachments.save_pages(item.id, 'hash', pages()+[{'page': 2, 'text': '', 'status': 'ocr_or_review_required'}])
    docs = with_attachments([as_document(row)], '서류')
    assert len(docs) == 2 and '읽지 못한 페이지' in docs[1].chunk_text


def test_same_file_on_other_department_keeps_ownership():
    one, a, _ = parent(category='A학과')
    two, b, _ = parent(URL+'2', category='B학과')
    attachments.save_pages(a.id, 'same', pages())
    attachments.save_pages(b.id, 'same', pages())
    docs = with_attachments([as_document(one)], '서류')
    assert all(d.category == 'A학과' for d in docs)
    with db.session_scope() as session:
        assert session.scalar(select(func.count()).select_from(db.AttachmentPage)) == 2


def test_download_does_not_follow_external_redirect_or_accept_oversize(monkeypatch):
    monkeypatch.setattr(attachments.time, 'sleep', lambda _: None)
    for response in [httpx.Response(302, headers={'location': 'https://evil.example/a.pdf'}),
                     httpx.Response(200, headers={'content-length': str(attachments.MAX_BYTES+1)})]:
        fetcher = attachments.AttachmentFetcher()
        fetcher.client.close()
        calls = []
        def handler(request):
            calls.append(str(request.url))
            if request.url.path == '/robots.txt':return httpx.Response(404)
            return response
        fetcher.client = httpx.Client(transport=httpx.MockTransport(handler))
        with pytest.raises(ValueError): fetcher.download(FILE)
        assert not any('evil.example' in url for url in calls)
        fetcher.close()


def test_extractor_flags_scanned_page_and_keeps_table_cells(monkeypatch):
    import pdfplumber
    from app.attachment_extract import extract_pdf
    def page(images):
        return SimpleNamespace(extract_text=lambda **kw: 'Synthetic readable document with requirements',
             extract_tables=lambda: [[['Course', 'Credits'], ['Test course', '3']]], images=images,
             width=100, height=100, close=lambda: None)
    class PDF:
        pages = [page([]), page([{'x0': 0, 'x1': 100, 'top': 0, 'bottom': 95}])]
        def __enter__(self):return self
        def __exit__(self, *args):pass
    monkeypatch.setattr(pdfplumber, 'open', lambda *args: PDF())
    result = extract_pdf(b'%PDF-test')
    assert 'Test course | 3' in result[0]['text']
    assert result[1]['status'] == 'ocr_or_review_required' and not result[1]['text']
