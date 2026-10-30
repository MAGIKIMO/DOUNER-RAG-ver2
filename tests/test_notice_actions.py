from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from fastapi import HTTPException
from app import db,notice_actions

@pytest.fixture(autouse=True)
def database(monkeypatch):
    engine=create_engine('sqlite://',poolclass=StaticPool)
    monkeypatch.setattr(db,'engine',lambda:engine);db.init_db();yield;engine.dispose()

def notice(content='신청서와 재학증명서를 제출하세요.'):
    db.save_notice(source='test',source_type='notice',category='일반공지',title='프로그램 모집',url='https://www.donga.ac.kr/notice',content=content)
    with db.session_scope() as session:return session.query(db.Notice).first().id

def test_version_ignores_recrawl_and_detects_body_change():
    i=notice();first=notice_actions.snapshot(i)
    notice();assert notice_actions.snapshot(i)['version']==first['version']
    notice('마감이 변경되었습니다. 신청서를 제출하세요.')
    assert notice_actions.snapshot(i)['version']!=first['version']

def test_steps_require_exact_evidence_and_valid_document():
    docs=[SimpleNamespace(chunk_text='신청서와 재학증명서를 제출하세요.',title='공지',url='https://www.donga.ac.kr/')]
    valid={'text':'서류 준비','quote':'신청서와 재학증명서','source':1}
    assert len(notice_actions.validated_steps([valid,{**valid,'quote':'존재하지 않는 제출 서류'},{**valid,'source':99}],docs))==1

def test_draft_no_database_task_write_and_graceful_failure(monkeypatch):
    i=notice()
    monkeypatch.setattr(notice_actions,'generate_answer',lambda *a:'{"steps":[{"text":"서류 준비","quote":"신청서와 재학증명서","source":1}]}')
    draft=notice_actions.draft(i)
    assert draft['requires_confirmation'] and len(draft['steps'])==1
    assert draft['deadline']['date'] is None
    assert notice_actions.changes(notice_actions.WatchRequest(ids=[i,999]))['items'][1]['unavailable']

def test_attachment_replacement_changes_version():
    i=notice();old=notice_actions.snapshot(i)['version']
    with db.session_scope() as session:session.add(db.Attachment(id='file',parent_id=i,url='https://www.donga.ac.kr/a.pdf',filename='a.pdf',file_hash='one'))
    assert notice_actions.snapshot(i)['version']!=old
    before=notice_actions.snapshot(i)['version']
    with db.session_scope() as session:session.get(db.Attachment,'file').file_hash='two'
    assert notice_actions.snapshot(i)['version']!=before

def test_provider_failure_falls_back_to_verbatim_action_lines(monkeypatch):
    i=notice()
    def fail(*args):raise RuntimeError('provider unavailable')
    monkeypatch.setattr(notice_actions,'generate_answer',fail)
    result=notice_actions.draft(i)
    assert result['draft_status']=='source_excerpt'
    assert result['steps'][0]['quote']=='신청서와 재학증명서를 제출하세요.'
