import importlib.util
from pathlib import Path
import pytest


spec = importlib.util.spec_from_file_location('demo_verify', Path(__file__).parents[1] / 'scripts' / 'verify_demo.py')
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


@pytest.mark.parametrize('data', [None, [], {'status': 'ok', 'components': []},
    {'status': 'degraded', 'components': {'api':'ok', 'mysql':'ok', 'chroma':'ok', 'index':'empty'}}])
def test_http_200_does_not_prove_readiness(monkeypatch, data):
    monkeypatch.setattr(verify, 'request', lambda *a, **k: {'http':200, 'seconds':.01, 'data':data})
    assert not verify.preflight('http://localhost:8080', 1)[0]['passed']


def test_old_running_build_is_not_accepted(monkeypatch):
    data = {'status':'ok','components':{'api':'ok','mysql':'ok','chroma':'ok','index':'ready'}}
    monkeypatch.setattr(verify, 'request', lambda *a, **k: {'http':200,'seconds':.01,'data':data})
    results = verify.preflight('http://localhost:8080', 1, 'expected')
    assert results[0]['passed'] and not results[1]['passed']


def test_citation_numbers_do_not_become_accuracy(monkeypatch):
    data = {'answer':'Something [99]', 'sources':[{'id':1}], 'debug_info':{'status':'ok'}}
    monkeypatch.setattr(verify,'request',lambda *a,**k:{'http':200,'seconds':.01,'data':data})
    result = verify.run_case('http://localhost:8080', {'id':'x','question':'x'}, 1)
    assert result['response_valid'] and not result['citation_ids_valid']
    assert result['manual_answer_correct'] is None
    assert verify.summarize([result])['answer_accuracy'] is None


def test_runner_and_server_fingerprint_the_same_sources():
    from app.build_info import BUILD_ID
    assert verify.local_build_id() == BUILD_ID


@pytest.mark.parametrize('status,route', [('clarification_required','exam_schedule'), ('llm_fallback','academic_calendar')])
def test_http_200_and_valid_citations_do_not_pass_wrong_behavior(monkeypatch, status, route):
    data = {'answer':'Which department? [1]', 'sources':[{'id':1}],
            'debug_info':{'status':status,'retrieval_mode':route}, 'answer_language':'en'}
    monkeypatch.setattr(verify,'request',lambda *a,**k:{'http':200,'seconds':.01,'data':data})
    case = {'id':'calendar-en','question':'Final exams?', 'expected_route':'academic_calendar',
            'expected_statuses':['ok'], 'expected_language':'en'}
    result = verify.run_case('http://localhost:8080', case, 1)
    assert result['response_valid'] and result['citation_ids_valid']
    assert not result['behavior_passed']
    assert verify.summarize([result])['behavior_checks_passed'] == 0


def test_metadata_check_is_not_language_or_answer_correctness(monkeypatch):
    data = {'answer':'Some text', 'sources':[], 'debug_info':{'status':'ok','retrieval_mode':'academic_calendar'}, 'answer_language':'en'}
    monkeypatch.setattr(verify,'request',lambda *a,**k:{'http':200,'seconds':.01,'data':data})
    result = verify.run_case('http://localhost:8080', {'id':'x','question':'x','expected_statuses':['ok'],'expected_language':'en'}, 1)
    assert result['behavior_passed']
    assert result['manual_language_correct'] is None and result['manual_answer_correct'] is None
