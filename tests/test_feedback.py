from uuid import uuid4
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from app import db, feedback, main


@pytest.fixture
def client(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    monkeypatch.setattr(db, 'engine', lambda: engine)
    monkeypatch.setenv('ADMIN_API_KEY', 'test-admin-key')
    db.init_db()
    feedback._attempts.clear()
    yield TestClient(main.app)
    engine.dispose()


def report():
    return {'client_id': str(uuid4()), 'question': '테스트 질문', 'answer': '검증용 답변',
            'reason': 'wrong_answer', 'comment': '정정 요청',
            'sources': [{'title': '테스트 문서', 'url': 'https://example.org/notice'}]}


def test_report_persists_and_admin_listing_is_protected(client):
    payload = report()
    response = client.post('/api/v1/feedback', json=payload)
    assert response.status_code == 201
    with db.session_scope() as session:
        row = session.get(feedback.Feedback, response.json()['id'])
        assert row.question == payload['question']
        assert row.answer == payload['answer']
        assert json.loads(row.sources) == payload['sources']
    assert client.get('/api/v1/admin/feedback').status_code in (401, 403)
    response = client.get('/api/v1/admin/feedback', headers={'X-Admin-Key': 'test-admin-key'})
    assert response.status_code == 200
    assert '정정 요청' in response.text


def test_invalid_report_is_not_saved(client):
    for changes in [{'reason': 'unknown'}, {'answer': ''}, {'comment': 'x'*1001}, {'client_id': 'bad'}]:
        assert client.post('/api/v1/feedback', json={**report(), **changes}).status_code == 422
    with db.session_scope() as session:
        assert session.scalar(select(feedback.Feedback)) is None


def test_report_limit_is_per_browser(client):
    payload = report()
    for _ in range(10):
        assert client.post('/api/v1/feedback', json=payload).status_code == 201
    assert client.post('/api/v1/feedback', json=payload).status_code == 429
    assert client.post('/api/v1/feedback', json=report()).status_code == 201
