from datetime import datetime, timezone
from app.personal_brief import briefing
from app.canvas_lms import CanvasError


class Canvas:
    origin='https://canvas.donga.ac.kr'
    def courses(self):return {'complete':True,'courses':[{'id':'1','name':'Course'}]}
    def listing(self,path,params):
        return {'complete':True,'items':[
            {'id':'11','course_id':'1','name':'Pending','due_at':'2026-09-24T00:00:00Z','submission':{'workflow_state':'unsubmitted'}},
            {'id':'12','course_id':'1','name':'Done','due_at':'2026-09-24T00:00:00Z','submission':{'workflow_state':'submitted'}},
            {'id':'13','course_id':'1','name':'Unknown','due_at':'2026-09-24T01:00:00Z'},
            {'id':'14','course_id':'1','name':'Undated','due_at':None},
            {'id':'15','course_id':'1','name':'Old','due_at':'2026-09-20T00:00:00Z'},
            {'id':'16','course_id':'99','name':'Wrong course','due_at':'2026-09-24T00:00:00Z'},
            {'id':'17','course_id':'1','name':'Far','due_at':'2026-10-24T00:00:00Z'}]}


def test_due_window_submission_and_timezone():
    result=briefing(Canvas(),datetime(2026,9,23,tzinfo=timezone.utc))
    assert [d['title'] for d in result['deadlines']]==['Pending','Unknown']
    assert result['deadlines'][0]['due_at']=='2026-09-24T09:00:00+09:00'
    assert result['deadlines'][1]['submission_state']=='unknown'
    assert result['undated_assignments']==1 and result['complete']
    assert not result['timetable_available']


def test_fetch_failure_not_empty_success():
    class Broken(Canvas):
        def listing(self,*args):raise CanvasError('request_timeout')
    result=briefing(Broken())
    assert not result['complete'] and result['failures'] and not result['deadlines']


def test_course_limit_is_disclosed():
    class Many(Canvas):
        def courses(self):return {'complete':True,'courses':[{'id':str(i),'name':'Course'} for i in range(1,15)]}
        def listing(self,*args):return {'complete':True,'items':[]}
    result=briefing(Many())
    assert result['courses_checked']==12 and result['course_count']==14 and not result['complete']
