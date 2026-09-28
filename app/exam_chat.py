"""Route exam timetable questions to dated notices, not loose vector matches."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .db import Notice, session_scope
from .document_context import as_document

INTENT = re.compile(r'중간\s*고사|기말\s*고사|중간\s*시험|기말\s*시험|시험\s*시간표')


def answer_exam(question, language='ko', filters=None, context=None):
    context = dict(context or {})
    pending = context.get('pending_question', '') or ''
    # Let feelings/study advice continue through the conversational router.
    if re.search(r'힘들|싫|걱정|불안|망했|스트레스|공부법|공부\s*방법', question) and not re.search(r'시간표|일정|언제|몇\s*시|강의실|공지|관련', question):
        return None
    if not INTENT.search(question) and not INTENT.search(pending):
        return None
    with session_scope() as session:
        names = set(session.scalars(select(Notice.category).distinct()))
    names.update({'컴퓨터공학과', 'AI학과'})
    explicit = next((n for n in sorted(names, key=len, reverse=True) if n in question), None)
    if '컴공' in question:
        explicit = '컴퓨터공학과'
    followup = bool(INTENT.search(pending) and explicit and len(question) < 100)
    if not INTENT.search(question) and not followup:
        return None
    original = pending if followup else question
    department = explicit or (filters or {}).get('category') or context.get('department')
    if department and not (department.endswith('학과') or department.endswith('학부')):
        department = None
    debug = {'retrieval_mode': 'exam_schedule', 'status': 'clarification_required'}
    if not department:
        prompts = {'ko': '어느 학과의 중간·기말고사 시간표를 볼까요? 예: 컴퓨터공학과. 학과를 알려주시면 시험 날짜·시간·강의실을 확인해 드릴게요.',
                   'en': 'Which department’s exam timetable do you need?', 'ja': 'どの学科の試験時間割ですか？', 'zh': '您想查询哪个学科的考试安排？'}
        return {'answer': prompts[language], 'sources': [], 'debug_info': debug,
                'conversation_context': {'pending_question': original}}
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    year_match = re.search(r'20\d{2}', original)
    term_match = re.search(r'([12])\s*학기', original)
    year = year_match.group() if year_match else str(now.year)
    term = term_match.group(1) if term_match else ('1' if now.month < 8 else '2')
    kind = '기말고사' if re.search(r'기말', original) else '중간고사'
    with session_scope() as session:
        rows = list(session.scalars(select(Notice).where(
            Notice.source_type == 'notice', Notice.category == department,
            Notice.title.contains(year), Notice.title.contains(term + '학기'),
            Notice.title.contains(kind), Notice.title.contains('시간표')
        ).order_by(Notice.published_at.desc(), Notice.id.desc()).limit(1)))
    debug.update(department=department, year=year, term=term, status='ok')
    state = {'department': department}
    if not rows:
        debug['status'] = 'exam_not_collected'
        return {'answer': f'{department}의 {year}년 {term}학기 {kind} 시간표가 현재 수집된 자료에서 확인되지 않습니다. 공지가 없다는 뜻은 아니며, 자료 갱신 여부를 확인해야 합니다.',
                'sources': [], 'debug_info': debug, 'conversation_context': state}
    from .rag_service import compose_answer
    scoped = f'{original}\n확인 범위: {department}, {year}년 {term}학기 {kind}. 다른 학과·분반을 섞지 말고, 개인 과목·분반이 없으면 확인된 개요를 설명한 뒤 필요한 정보를 물어보세요.'
    result = compose_answer(scoped, [as_document(rows[0])], language, debug)
    result['conversation_context'] = state
    return result
