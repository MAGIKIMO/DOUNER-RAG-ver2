"""Deterministic owner briefing. No invented class/exam dates or LLM calls."""
from datetime import datetime, timedelta, timezone
from .canvas_lms import CanvasError, KST, identifier, local_time


def briefing(client, now=None):
    now = now or datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    courses = client.courses()
    deadlines, undated, failures = [], 0, []
    selected = courses['courses'][:12]
    for course in selected:
        cid = identifier(course['id'])
        try:
            result = client.listing(f'/api/v1/courses/{cid}/assignments', {'include[]':'submission'})
            if not result['complete']:
                failures.append({'course':course['name'], 'reason':'partial_page_limit'})
            for row in result['items']:
                if row.get('course_id') and str(row['course_id']) != cid:
                    continue
                submission = row.get('submission') or {}
                if submission.get('excused') or submission.get('workflow_state') in ('submitted','graded'):
                    continue
                due = local_time(row.get('due_at'))
                if not due:
                    undated += 1
                    continue
                at = datetime.fromisoformat(due)
                if now <= at <= end and row.get('id'):
                    deadlines.append({'course':course['name'], 'course_id':cid, 'title':str(row.get('name') or '제목 미제공'),
                        'due_at':due,'submission_state':submission.get('workflow_state') or 'unknown',
                        'url':client.origin+f'/courses/{cid}/assignments/'+identifier(row['id'])})
        except CanvasError:
            failures.append({'course':course['name'], 'reason':'fetch_failed'})
    deadlines.sort(key=lambda item:item['due_at'])
    return {'fetched_at':now.astimezone(KST).isoformat(), 'days':7,
        'course_count':len(courses['courses']), 'courses_checked':len(selected),
        'complete':courses['complete'] and len(selected)==len(courses['courses']) and not failures,
        'failures':failures,'undated_assignments':undated,'deadlines':deadlines,
        'timetable_available':False}
