from types import SimpleNamespace as Obj
from app import rag_service
from app.exam_fallback import excerpt_answer
from app.llm_provider import LLMError


def test_quota_failure_keeps_verified_exam_rows(monkeypatch):
    from app import document_context
    text = '첨부파일: 시험.xlsx\n[원본 행 8] 강의명: 운영체제 | 시험 시작시간: 16:30'
    doc = Obj(source_id=1, source_type='attachment', title='시험.xlsx', category='컴퓨터공학과',
              url='https://example.com/exam.xlsx', published_at=None, chunk_text=text)
    monkeypatch.setattr(document_context, 'with_attachments', lambda docs,*a,**k:docs)
    def fail(*args): raise LLMError('quota_exceeded')
    monkeypatch.setattr(rag_service, 'generate_answer', fail)
    result = rag_service.compose_answer('운영체제 중간고사', [doc], 'ko', {'retrieval_mode':'exam_schedule'})
    assert result['debug_info']['status'] == 'source_excerpt'
    assert '16:30' in result['answer'] and '원문' in result['answer']
    assert len(result['sources']) == 1


def test_no_schedule_is_invented_from_unstructured_text():
    assert excerpt_answer([{'title':'공지', 'text':'첨부파일 확인', 'source':1}], 'ko') is None


def test_common_calendar_is_labeled_and_other_language_is_not_fake_translation():
    docs = [{'title':'학사일정', 'text':'2026학년도 학교 공통 학사일정\n2학기 | 2026.10.20~10.26 | 제2학기 중간시험', 'source':2}]
    answer = excerpt_answer(docs, 'en')
    assert 'original source language' in answer
    assert 'University-wide period' in answer
    assert '[2]' in answer


def test_pdf_text_survives_provider_failure_and_is_marked_excerpt():
    content = '첨부파일: exam.pdf\n[원본 1쪽] 전기공학과 시험시간표\n' + '회로이론 10/20 13:00 공학관\n' * 400
    answer = excerpt_answer([{'title':'exam.pdf', 'text':content, 'source':2}], 'ko', 'provider_unavailable')
    assert '일시적인 서버 오류' in answer
    assert '회로이론' in answer and '[2]' in answer
    assert 'Partial excerpt' in answer
    assert len(answer) < 3500


def test_pdf_pages_remain_separate():
    answer = excerpt_answer([{'title':'exam.pdf','source':1,
        'text':'첨부파일: exam.pdf\n[원본 1쪽] 회로이론 13:00\n[원본 2쪽] 전자기학 15:00'}], 'en')
    assert '[원본 1쪽]' in answer and '[원본 2쪽]' in answer
    assert 'original source language' in answer


def test_unstructured_pdf_is_collapsed_in_api_result(monkeypatch):
    from app import document_context
    doc = Obj(source_id=1, source_type='attachment', title='시험.pdf', category='전기공학과',
              url='https://example.com/exam.pdf', published_at=None,
              chunk_text='[원본 1쪽] 복잡한 시간표 원문 13:00')
    monkeypatch.setattr(document_context,'with_attachments',lambda docs,*a,**k:docs)
    def fail(*args): raise LLMError('provider_unavailable')
    monkeypatch.setattr(rag_service,'generate_answer',fail)
    result=rag_service.compose_answer('중간고사',[doc],'ko',{'retrieval_mode':'exam_schedule'})
    assert result['debug_info']['status']=='source_preview'
    assert '13:00' not in result['answer']
    assert '13:00' in result['source_excerpts'][0]['text']
