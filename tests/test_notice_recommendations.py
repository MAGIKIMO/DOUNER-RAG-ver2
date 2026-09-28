from datetime import datetime
from types import SimpleNamespace
from app.notice_recommendations import deadline, rank, Preferences

NOW=datetime(2026,9,28,12)


def row(id=1,**kwargs):
    return SimpleNamespace(**dict(dict(id=id,title='장학금 신청 안내',category='동아광장',url='https://www.donga.ac.kr/'+str(id),
        content='지원 대상: 재학생\n신청 마감: 2026.10.05까지',published_at=NOW,crawled_at=NOW),**kwargs))


def test_full_date_and_past_classification():
    assert deadline('신청 마감: 2026.09.27까지',NOW.date())['status']=='past_date'
    assert deadline('접수 기간: 2026.09.28 ~ 2026.10.05',NOW.date())['date']=='2026-10-05'


def test_abbreviated_conflicting_and_non_application_dates_unknown():
    for text in ['신청 기간: 2026.09.28 ~ 10.05','신청 마감: 9월 30일','게시일: 2026.09.28',
                 '신청 마감: 2026.10.01\n서류 제출 마감: 2026.10.02','신청 기간: 2026.09.28 - 10.05']:
        assert deadline(text,NOW.date())['status']=='unknown'


def test_excludes_other_departments_future_publication_and_expired():
    rows=[row(1,category='컴퓨터공학과'),row(2,category='AI학과'),row(3,published_at=datetime(2026,10,1)),
          row(4,content='신청 마감: 2026.09.01까지')]
    result=rank(rows,Preferences(department='컴퓨터공학과',interests=['scholarship']),NOW)
    assert [r['id'] for r in result]==[1]
    assert result[0]['reasons']==['선택한 학과 공지','관심 분야: 장학금']


def test_deduplicates_titles_and_unknown_deadlines_stay_visible():
    result=rank([row(1,content='장학금 안내: 신청 기한 별도 공지'),row(2)],Preferences(interests=['scholarship']),NOW)
    assert len(result)==1 and result[0]['deadline']['status']=='unknown'
    assert '장학금 안내' in result[0]['excerpt']


def test_no_preferences_does_not_make_arbitrary_recommendations():
    assert rank([row()],Preferences(),NOW)==[]
