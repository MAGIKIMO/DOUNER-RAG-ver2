from datetime import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app import db, rag_service
from app.main import app
from app.canvas_lms import KST


@pytest.fixture
def client(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    monkeypatch.setattr(db,'engine',lambda:engine);db.init_db()
    db.save_notice(source='University',source_type='notice',category='동아광장',title='장학금 모집',content='지원 대상: 재학생. 성적 및 소득 조건은 별도 확인.',url='https://www.donga.ac.kr/test',published_at=datetime.now(KST).replace(tzinfo=None))
    yield TestClient(app)
    engine.dispose()


def test_recommend_api_and_validation(client):
    r=client.post('/api/v1/notices/recommend',json={'interests':['scholarship']})
    assert r.status_code==200 and len(r.json()['items'])==1
    assert r.json()['items'][0]['deadline']['status']=='unknown'
    assert client.post('/api/v1/notices/recommend',json={'interests':['invalid']}).status_code==422


def test_summary_uses_selected_body_and_static_ids_are_not_notices(client,monkeypatch):
    seen=[]
    monkeypatch.setattr(rag_service,'compose_answer',lambda q,docs,*args: seen.append(docs) or {'answer':'checked','sources':[]})
    assert client.post('/api/v1/notices/1/summary').json()['answer']=='checked'
    assert seen[0][0].url=='https://www.donga.ac.kr/test'
    assert '지원 대상' in seen[0][0].chunk_text
    assert client.post('/api/v1/notices/999/summary').status_code==404
