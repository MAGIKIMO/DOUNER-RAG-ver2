import json
from datetime import datetime

import httpx
import pytest

from app import canvas_assistant as assistant, canvas_lms, rag_service, db

NOW = datetime.fromisoformat('2026-10-22T10:00:00+09:00')
ORIGIN = 'https://canvas.donga.ac.kr'
TOKEN = 'synthetic-owner-token'


def assignment(aid, due='2026-10-25T14:59:00Z', state='unsubmitted', **extras):
    row = {'id':aid, 'name':f'과제 {aid}', 'description':'<p>보고서 두 쪽을 PDF로 제출하세요.</p>',
           'due_at':due, 'submission_types':['online_upload'], 'submission':{'workflow_state':state}}
    row.update(extras)
    return row


def make_client(assignments=None, announcements=None, courses=None, fail=None, partial=False):
    calls = []
    courses = courses if courses is not None else [{'id':'1','name':'운영체제 (01분반)'}, {'id':'2','name':'자료구조'}]
    assignments = assignments or {}
    announcements = announcements or {}
    def handler(request):
        assert request.method == 'GET'
        assert request.headers['Authorization'] == 'Bearer '+TOKEN
        assert TOKEN not in str(request.url)
        calls.append(request)
        path = request.url.path
        if path == '/api/v1/courses':
            return httpx.Response(200,json=courses)
        if path == '/api/v1/announcements':
            cid = request.url.params['context_codes[]'].split('_')[1]
            return httpx.Response(200,json=announcements.get(cid,[]))
        cid = path.split('/')[4]
        assert request.url.params['include[]']=='submission'
        if cid == fail:
            return httpx.Response(503)
        headers = {'Link':f'<{ORIGIN}{path}?page=2>; rel="next"'} if partial else {}
        return httpx.Response(200,json=assignments.get(cid,[]),headers=headers)
    return canvas_lms.CanvasClient(ORIGIN,TOKEN,transport=httpx.MockTransport(handler)), calls


@pytest.fixture(autouse=True)
def no_shared_storage(monkeypatch):
    monkeypatch.setattr(db,'session_scope',lambda:pytest.fail('Personal data reached shared DB'))


def test_all_courses_week_boundary_and_zero_llm(monkeypatch):
    monkeypatch.setattr(rag_service,'generate_answer',lambda *a:pytest.fail('Simple deadline question called LLM'))
    api,calls = make_client({'1':[assignment('11'),assignment('12',state='submitted'),
                                 assignment('13','2026-10-25T15:00:00Z'),assignment('14',None)],
                            '2':[assignment('21','2026-10-21T14:59:00Z'),assignment('22',course_id='99')]})
    try:
        result = assistant.ask_personal(api,'이번 주 안 낸 과제 뭐 있어?',now=NOW)
    finally:
        api.close()
    assert result['counts']=={'pending':2,'uncertain':0,'undated':1}
    assert result['period']['start']=='2026-10-19T00:00:00+09:00'
    assert result['period']['end']=='2026-10-26T00:00:00+09:00'
    assert '기한 경과' in result['answer'] and '2026-10-25 23:59' in result['answer']
    assert '과제 12' not in result['answer'] and '과제 13' not in result['answer'] and '과제 22' not in result['answer']
    assert result['coverage']['complete'] and len(calls)==3  # course list once + 2 assignment endpoints
    assert all('/announcements' not in str(r.url) for r in calls)
    assert TOKEN not in json.dumps(result)


@pytest.mark.parametrize('row,state',[
    ({'submission_state':'unsubmitted'}, 'unsubmitted'),
    ({'submission_state':None}, 'verify'),
    ({'submission_state':'unsubmitted','submission_types':['external_tool']}, 'external'),
    ({'submission_state':'unsubmitted','submission_types':['on_paper']}, 'external'),
    ({'submission_state':'submitted'}, 'submitted'),
    ({'submission_state':'pending_review'}, 'submitted'),
    ({'submission_state':'graded'}, 'graded'),
    ({'submission_state':'graded','missing':True}, 'unsubmitted'),
    ({'submission_state':'submitted','redo_request':True}, 'resubmit'),
    ({'submission_state':'unsubmitted','submitted_at':'2026-10-01T10:00:00+09:00'}, 'submitted'),
    ({'submission_state':'unsubmitted','excused':True}, 'excused'),
])
def test_submission_semantics(row,state):
    assert assistant.submission_status(row)==state


def test_external_unknown_redo_and_locked_are_distinguished():
    api,_ = make_client({'1':[
        assignment('1',state=None), assignment('2',submission_types=['external_tool']),
        assignment('3',submission={'workflow_state':'submitted','redo_request':True},locked_for_user=True),
        assignment('4',submission={'workflow_state':'unsubmitted','excused':True})]})
    try:
        result=assistant.ask_personal(api,'뭐부터 해야 해?',now=NOW)
    finally:api.close()
    assert result['counts']['pending']==1 and result['counts']['uncertain']==2
    assert '재제출 요청' in result['answer'] and '현재 접근 제한' in result['answer']
    assert '외부 도구' in result['answer'] and '과제 4' not in result['answer']


@pytest.mark.parametrize('question,start,end',[
    ('오늘 마감 과제','2026-10-22T00:00:00+09:00','2026-10-23T00:00:00+09:00'),
    ('내일 과제','2026-10-23T00:00:00+09:00','2026-10-24T00:00:00+09:00'),
    ('다음 주 과제','2026-10-26T00:00:00+09:00','2026-11-02T00:00:00+09:00'),
    ('앞으로 7일 과제','2026-10-22T10:00:00+09:00','2026-10-29T10:00:00+09:00'),
])
def test_calendar_and_rolling_periods(question,start,end):
    a,b=assistant.time_window(question,NOW)
    assert a.isoformat()==start and b.isoformat()==end


@pytest.mark.parametrize('language,question,word',[
    ('en','What assignments are unsubmitted this week?','Unsubmitted'),
    ('ja','今週の未提出課題は？','未提出'),
    ('zh','本周未提交的作业有哪些？','未提交'),
    ('ko','이번 주 미제출 과제','미제출'),
])
def test_multilingual_task_questions(language,question,word):
    api,_=make_client({'1':[assignment('1')]})
    try:result=assistant.ask_personal(api,question,now=NOW)
    finally:api.close()
    assert result['language']==language and word in result['answer']
    assert result['counts']['pending']==1
    assert result['period']['end']=='2026-10-26T00:00:00+09:00'


def test_partial_error_never_claims_complete_absence():
    api,_=make_client(fail='2')
    try:result=assistant.ask_personal(api,'이번 주 과제',now=NOW)
    finally:api.close()
    assert not result['coverage']['complete'] and result['status']=='partial'
    assert '전체 목록은 아닙니다' in result['answer']
    assert result['coverage']['failures'][0]['course']=='자료구조'


def test_page_limit_and_course_cap_visible(monkeypatch):
    monkeypatch.setattr(canvas_lms,'MAX_PAGES',1)
    api,_=make_client(partial=True)
    try:result=assistant.ask_personal(api,'미제출 과제',now=NOW)
    finally:api.close()
    assert not result['coverage']['complete']
    api,calls=make_client(courses=[{'id':str(i),'name':f'Course {i}'} for i in range(1,15)])
    try:result=assistant.ask_personal(api,'미제출 과제',now=NOW)
    finally:api.close()
    assert result['coverage']['courses_total']==14 and result['coverage']['courses_checked']==12
    assert result['status']=='partial' and len(calls)==13


def test_course_name_selects_only_own_course_and_real_body(monkeypatch):
    announcements={'1':[{'id':'11','context_code':'course_1','title':'보고서 안내','message':'<p>보고서를 두 쪽 작성해 PDF로 제출하세요.</p>','posted_at':'2026-10-22T00:00:00Z'}]}
    def generate(system,user):
        payload=json.loads(user)
        assert 'Korean' in system
        assert all(d['course']=='운영체제 (01분반)' for d in payload['documents'])
        assert '보고서를 두 쪽' in payload['documents'][0]['text']
        return '보고서를 두 쪽 작성해 PDF로 제출하세요. [1]'
    monkeypatch.setattr(rag_service,'generate_answer',generate)
    api,calls=make_client(announcements=announcements)
    try:result=assistant.ask_personal(api,'운영체제 새 공지 요약해 줘',now=NOW)
    finally:api.close()
    assert result['status']=='ok' and 'PDF' in result['answer']
    assert len(calls)==2 and calls[-1].url.params['context_codes[]']=='course_1'


def test_ambiguous_unknown_course_and_unauthorized_id_do_not_fetch_bodies():
    api,calls=make_client(courses=[{'id':'1','name':'운영체제 (01)'},{'id':'2','name':'운영체제 (02)'}])
    try:
        assert assistant.ask_personal(api,'운영체제 공지 요약')['status']=='needs_course'
        assert assistant.ask_personal(api,'없는과목 공지 요약')['status']=='needs_course'
        assert assistant.ask_personal(api,'물리학 과제 뭐 있어?')['status']=='needs_course'
        assert assistant.ask_personal(api,'Any assignments for Physics?')['status']=='needs_course'
        assert assistant.ask_personal(api,'이 과목 설명해줘')['status']=='needs_course'
        with pytest.raises(canvas_lms.CanvasError,match='course_not_available'):
            assistant.ask_personal(api,'과제',course_id='999')
        assert len(calls)==1
    finally:api.close()


def test_llm_context_bounded_and_failed_summary_is_explicit(monkeypatch):
    from app.llm_provider import LLMError
    def generate(system,user):
        data=json.loads(user)
        assert len(json.dumps(data['documents'],ensure_ascii=False))<=assistant.MAX_CONTEXT
        assert data['selection_incomplete']
        assert all(d['body_truncated'] for d in data['documents'])
        raise LLMError('timeout')
    monkeypatch.setattr(rag_service,'generate_answer',generate)
    api,_=make_client(announcements={'1':[{'id':str(i),'title':f'공지 {i}','message':'가'*6000,'posted_at':'2026-10-22T00:00:00Z'} for i in range(1,30)]})
    try:result=assistant.ask_personal(api,'전체 과목 최근 공지 요약해 줘',now=NOW)
    finally:api.close()
    assert result['status']=='llm_timeout' and '본문 일부' in result['answer']
    assert len(result['sources'])<=3 and len(result['answer'])<1800


def test_explicit_unsupported_date_not_silently_treated_as_all_dates():
    api,calls=make_client()
    try:result=assistant.ask_personal(api,'11월 과제 마감',now=NOW)
    finally:api.close()
    assert result['status']=='needs_period' and len(calls)==1


def test_notice_period_and_four_language_prompts(monkeypatch):
    announcements={'1':[
        {'id':'1','title':'이전 공지','message':'OLD_BODY','posted_at':'2026-10-18T00:00:00Z'},
        {'id':'2','title':'새 공지','message':'CURRENT_BODY','posted_at':'2026-10-22T00:00:00Z'},
    ]}
    for language, name in [('ko','Korean'),('en','English'),('ja','Japanese'),('zh','Simplified Chinese')]:
        def generate(system,user):
            assert f'Answer in {name}.' in system
            assert 'CURRENT_BODY' in user and 'OLD_BODY' not in user
            return 'A supported summary. [1]'
        monkeypatch.setattr(rag_service,'generate_answer',generate)
        api,_=make_client(announcements=announcements)
        try:result=assistant.ask_personal(api,'운영체제 이번 주 공지 요약',language=language,now=NOW)
        finally:api.close()
        assert result['language']==language and result['status']=='ok'


def test_task_output_limit_does_not_hide_total():
    api,_=make_client({'1':[assignment(str(i)) for i in range(1,35)]})
    try:result=assistant.ask_personal(api,'미제출 과제',now=NOW)
    finally:api.close()
    assert result['counts']['pending']==34
    assert len(result['sources'])==assistant.MAX_ITEMS
    assert '34건 중 10건' in result['answer']


@pytest.mark.parametrize('question', ['오늘 마감할 일 뭐부터 해야 해?', 'What should I do first among assignments due today?',
                                    '今日締切の課題は何から？', '今天截止的作业先做什么？'])
def test_priority_respects_explicit_today(question):
    api, _ = make_client({'1': [assignment('1', '2026-10-22T14:59:00Z'),
                               assignment('2', '2026-10-23T00:00:00Z')]})
    try:
        result = assistant.ask_personal(api, question, course_id='1', now=NOW)
    finally:
        api.close()
    assert result['period']['start'] == '2026-10-22T00:00:00+09:00'
    assert result['period']['end'] == '2026-10-23T00:00:00+09:00'
    assert result['counts']['pending'] == 1
    assert '과제 2' not in result['answer']


@pytest.mark.parametrize('question', ['앞으로 17일 과제', 'Assignments for the next 17 days',
                                    '今後17日の課題', '未来17天的作业', '앞으로 3일 과제', '7일 마감 과제'])
def test_unsupported_day_range_never_silently_becomes_seven_days_or_all(question):
    api, calls = make_client({'1':[assignment('1')]})
    try:
        result = assistant.ask_personal(api, question, course_id='1', now=NOW)
    finally:
        api.close()
    assert result['status'] == 'needs_period'
    assert len(calls) == 1


@pytest.mark.parametrize('question', ['Physics assignments due this week?', '物理学の課題は？', '物理学的作业有哪些？'])
def test_unenrolled_course_in_four_language_tasks_is_not_all_courses(question):
    api, calls = make_client({'1':[assignment('1')]})
    try:
        result = assistant.ask_personal(api, question, now=NOW)
    finally:
        api.close()
    assert result['status'] == 'needs_course'
    assert len(calls) == 1


@pytest.mark.parametrize('question', ['앞으로 7일 미제출 과제', 'Unsubmitted assignments for the next 7 days',
                                    '今後7日の未提出課題', '未来7天未提交作业'])
def test_supported_rolling_week_still_works_without_course_selection(question):
    api, _ = make_client({'1':[assignment('1')]})
    try:
        result = assistant.ask_personal(api, question, now=NOW)
    finally:
        api.close()
    assert result['counts']['pending'] == 1
    assert result['period']['start'] == NOW.isoformat()
    assert result['period']['end'] == '2026-10-29T10:00:00+09:00'
