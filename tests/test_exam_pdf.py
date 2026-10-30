from app.exam_pdf import schedules, formatted_lines
from app.exam_fallback import excerpt_answer

TABLE = '''[표 1: 빈 셀은 원문 그대로이며 병합 관계를 추정하지 않음]
 | 월 | 화 | 수
 | 26일 | 20일 | 21일
 | | 09:00~10:30 / 교류기기 / 01,02분반 / 장정환 교수님 | 10:00~11:00 / 전기공학
 | | S04-0111 [01분반] / S04-0202 [02분반] | 실험및설계2 / 01분반 / 최호림 교수님 / S04-0203
 | | 10:30~12:00 / 응용전기자기학 / 01분반 | 
 | | 장정환 교수님 / S04-0111 |
'''

def test_days_courses_and_continuations_stay_in_their_columns():
    rows = schedules(TABLE)
    assert len(rows)==3
    assert rows[0]['course']=='교류기기' and rows[0]['date']=='20일(화)'
    assert rows[0]['time']=='09:00~10:30'
    assert 'S04-0202 [02분반]' in rows[0]['details']
    assert rows[-1]['course']=='전기공학 실험및설계2' and rows[-1]['date']=='21일(수)'
    assert '장정환' not in rows[-1]['details']

def test_course_section_and_readable_fallback():
    lines=formatted_lines(TABLE,'교류기기 02분반 시험 언제야?')
    answer=excerpt_answer([{'title':'시간표.pdf','text':'\n'.join(lines),'source':2}],'ko','provider_unavailable')
    assert '• 교류기기' in answer and '20일(화) · 09:00~10:30' in answer
    assert '[PDF 일정' not in answer
    assert '응용전기자기학' not in answer
    assert '확인하지 못함' in formatted_lines(TABLE,'교류기기 03분반')[0]

def test_missing_date_or_invalid_time_is_not_inferred():
    assert schedules(TABLE.replace('20일','미정'))[-1]['date']=='21일(수)'
    assert not any(r['course']=='교류기기' for r in schedules(TABLE.replace('09:00','29:00')))
    assert schedules('월 화 수\n20일 21일 22일\n교류기기 09:00')==[]
