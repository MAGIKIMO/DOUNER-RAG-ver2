from types import SimpleNamespace as Obj
from app.exam_context import compact_exam_files

def row(n, course):
    a=Obj(id='file',filename='exam.xlsx',url='https://example.com/exam.xlsx',checked_at=None,status='ok')
    r=Obj(id=n,source_type='attachment',category='컴퓨터공학과',title='long repeated title',url=a.url,
          published_at=None,crawled_at=None,content=f'엑셀 시간표 행 {n}\n시험 시간표 · 시트: 시간표\n강의명: {course}\n요일: 10/20\n시험 시작시간: 16:30\n강의실1: S06-0605\n강의실2: 원문 미기재')
    return r,Obj(page_number=n),a

def test_specific_course_only_and_one_file_citation():
    docs=compact_exam_files([row(1,'운영체제'),row(2,'컴퓨터네트워크')],'컴퓨터 네트워크 중간고사 언제야')
    assert len(docs)==1
    assert '컴퓨터네트워크' in docs[0].chunk_text
    assert '운영체제' not in docs[0].chunk_text
    assert '16:30' in docs[0].chunk_text
    assert docs[0].url=='https://example.com/exam.xlsx'

def test_general_schedule_budget_and_explicit_omission():
    docs=compact_exam_files([row(n,f'과목{n}') for n in range(40)],'중간고사 관련',budget=1000)
    assert len(docs)==1 and len(docs[0].chunk_text)<=1000
    assert '일부 행 생략' in docs[0].chunk_text
