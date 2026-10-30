"""Public localhost demo checks. Python stdlib only; never reads .env or LMS content.

Exit 0 means transport/readiness and configured behavior checks passed, NOT factual correctness.
Manual answer/source/language review is deliberately left ungraded.
"""
import argparse
import json
import math
import re
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(base, path, payload=None, timeout=75):
    started = time.perf_counter()
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    req = Request(base.rstrip('/') + path, data=body,
                  headers={'Content-Type': 'application/json'} if body is not None else {})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(2_000_001)
            status = response.status
    except HTTPError as exc:
        raw, status = exc.read(2_000_001), exc.code
    except (URLError, TimeoutError, OSError):
        return {'http': None, 'seconds': round(time.perf_counter()-started, 3), 'error': 'connection_or_timeout'}
    data = None
    if len(raw) <= 2_000_000:
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            pass
    return {'http': status, 'seconds': round(time.perf_counter()-started, 3), 'data': data}


def local_build_id():
    app_dir = Path(__file__).resolve().parent.parent / 'app'
    digest = hashlib.sha256()
    for path in sorted(app_dir.glob('*.py'), key=lambda p: p.name):
        digest.update(path.name.encode('utf-8') + b'\0')
        digest.update(path.read_bytes() + b'\0')
    return digest.hexdigest()[:20]


def preflight(base, timeout, expected_build=None):
    result = []
    heartbeat = request(base, '/api/v1/heartbeat', timeout=timeout)
    data = heartbeat.get('data') or {}
    ready = (isinstance(data, dict) and data.get('status') == 'ok'
             and isinstance(data.get('components'), dict)
             and all(data['components'].get(k) == v for k, v in
                     {'api': 'ok', 'mysql': 'ok', 'chroma': 'ok', 'index': 'ready'}.items()))
    result.append({'check': 'dependencies', 'passed': heartbeat['http'] == 200 and ready, **heartbeat})
    if expected_build:
        actual = data.get('build_id') if isinstance(data, dict) else None
        result.append({'check': 'running_build_matches_source', 'passed': actual == expected_build,
                       'expected': expected_build, 'actual': actual})
    for path in ('/chat.html', '/personal-demo.html', '/tasks.html', '/meals.html', '/manifest.webmanifest'):
        response = request(base, path, timeout=timeout)
        result.append({'check': path, 'passed': response['http'] == 200, 'http': response['http']})
    response = request(base, '/api/v1/ask', {'question': '   '}, timeout)
    result.append({'check': 'empty_question_rejected', 'passed': response['http'] == 422, 'http': response['http']})
    response = request(base, '/api/v1/personal-canvas/courses', timeout=timeout)
    # 503 is disabled/unconfigured: access is denied but the LMS demo is not ready.
    result.append({'check': 'anonymous_lms_denied', 'passed': response['http'] in (401, 403, 503), 'http': response['http']})
    return result


def run_case(base, case, timeout):
    payload = {'question': case['question'], 'language': case.get('language', 'auto')}
    response = request(base, '/api/v1/ask', payload, timeout)
    data = response.pop('data', None)
    valid = (response['http'] == 200 and isinstance(data, dict)
             and isinstance(data.get('answer'), str) and bool(data['answer'].strip())
             and isinstance(data.get('sources'), list)
             and all(isinstance(s, dict) for s in data['sources'])
             and isinstance(data.get('debug_info', {}), dict))
    result = {'id': case['id'], 'question': case['question'], 'language': payload['language'],
              **response, 'response_valid': valid, 'manual_checks': case.get('manual_checks', []),
              'manual_answer_correct': None, 'manual_citations_supported': None, 'manual_language_correct': None,
              'behavior_checks': {}, 'behavior_passed': False}
    if valid:
        answer = data['answer']
        ids = {str(s.get('id')) for s in data['sources']}
        citations = {n for group in re.findall(r'\[(\d+(?:\s*,\s*\d+)*)\]', answer) for n in re.findall(r'\d+', group)}
        result.update(answer=answer, sources=data['sources'], debug=data.get('debug_info', {}),
                      answer_language=data.get('answer_language'), source_count=len(data['sources']),
                      citation_ids_valid=citations <= ids,
                      # Matching strings are only a review aid, not an accuracy score.
                      expected_text_present={s: s.casefold() in answer.casefold() for s in case.get('expected_text', [])})
        debug = data.get('debug_info', {})
        checks = {'no_generation_or_retrieval_error': not debug.get('error_code') and
                  debug.get('status') not in ('llm_fallback', 'source_preview', 'unverified_answer', 'retrieval_unavailable')}
        if case.get('expected_statuses'):
            checks['expected_status'] = debug.get('status') in case['expected_statuses']
        if case.get('expected_route'):
            checks['expected_route'] = debug.get('retrieval_mode') == case['expected_route']
        if case.get('expected_language'):
            checks['expected_language_metadata'] = data.get('answer_language') == case['expected_language']
        result.update(behavior_checks=checks, behavior_passed=all(checks.values()))
    return result


def summarize(rows):
    times = sorted(r['seconds'] for r in rows)
    return {'requests': len(rows), 'valid_responses': sum(r['response_valid'] for r in rows),
            'behavior_checks_passed': sum(r.get('behavior_passed', False) for r in rows),
            'statuses': {status: sum(r.get('debug', {}).get('status') == status for r in rows)
                         for status in sorted({r.get('debug', {}).get('status') for r in rows} - {None})},
            'median_seconds': (times[(len(times)-1)//2] + times[len(times)//2])/2 if times else None,
            'p95_seconds': times[math.ceil(len(times)*.95)-1] if times else None,
            'answer_accuracy': None,
            'note': 'Response validity, citation IDs and expected substrings do not establish factual accuracy. Manual review required.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://localhost:8080')
    parser.add_argument('--cases', type=Path, default=Path(__file__).with_name('demo_cases.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=12)
    parser.add_argument('--timeout', type=int, default=75)
    parser.add_argument('--only-preflight', action='store_true')
    parser.add_argument('--case-id', action='append', default=[])
    parser.add_argument('--pause', type=float, default=15, help='Seconds between questions to reduce request bursts')
    parser.add_argument('--baseline', action='store_true', help='Record an older server without requiring matching source build')
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if url.scheme != 'http' or url.hostname not in ('localhost', '127.0.0.1') or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
        parser.error('Use a local HTTP origin, e.g. http://localhost:8080')
    if not 1 <= args.limit <= 50 or not 1 <= args.timeout <= 180 or not 0 <= args.pause <= 120:
        parser.error('limit must be 1..50, timeout 1..180 and pause 0..120')
    report = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'preflight': preflight(args.base_url, args.timeout, None if args.baseline else local_build_id()), 'cases': []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        report['summary'] = summarize(report['cases'])
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save()
    print(json.dumps({'preflight': report['preflight']}, ensure_ascii=False), flush=True)
    if not all(row['passed'] for row in report['preflight']):
        return 2
    if not args.only_preflight:
        cases = json.loads(args.cases.read_text(encoding='utf-8'))
        if args.case_id:
            unknown = set(args.case_id) - {c['id'] for c in cases}
            if unknown:
                parser.error('Unknown case IDs: ' + ', '.join(sorted(unknown)))
            cases = [c for c in cases if c['id'] in args.case_id]
        for case in cases[:args.limit]:
            if report['cases']:
                time.sleep(args.pause)
            row = run_case(args.base_url, case, args.timeout)
            report['cases'].append(row)
            save()
            print(json.dumps({'id': row['id'], 'http': row['http'], 'seconds': row['seconds'],
                              'status': row.get('debug', {}).get('status')}, ensure_ascii=False), flush=True)
            if row.get('debug', {}).get('error_code') == 'quota_exceeded':
                report['stopped_reason'] = 'quota_exceeded; remaining cases not run'
                save()
                return 2
    return 0 if all(r['response_valid'] and r.get('citation_ids_valid', True) and r['behavior_passed'] for r in report['cases']) else 2


if __name__ == '__main__':
    raise SystemExit(main())
