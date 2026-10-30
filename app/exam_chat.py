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
    previous_exam = context.get('exam_question', '') or ''
    short_followup = (bool(previous_exam) and context.get('last_route') != 'chat' and len(question) < 100
                      and bool(re.search(r'강의실|시험장소|몇\s*시|\d+\s*분반|\d+\s*학년|학과는|학부는|언제야|언제예요|기말은|중간은', question))
                      and not re.search(r'식단|학식|장학|졸업|등록금|휴학|도서관', question))
    if not INTENT.search(question) and not INTENT.search(pending) and not short_followup:
        return None
    with session_scope() as session:
        names = {name for name in session.scalars(select(Notice.category).distinct())
                 if name and name.endswith(('학과', '학부', '전공'))}
    names.update({'컴퓨터공학과', 'AI학과'})
    import json
    from .public_catalog import CATALOG
    from .exam_matching import matches
    names.update(s['department'] for s in json.loads(CATALOG.read_text(encoding='utf-8'))['sources'] if s.get('department'))
    explicit = next((n for n in sorted(names, key=len, reverse=True) if n in question), None)
    if '컴공' in question:
        explicit = '컴퓨터공학과'
    followup = bool(INTENT.search(pending) and explicit and len(question) < 100)
    if not INTENT.search(question) and not followup and not short_followup:
        return None
    original = pending if followup else (previous_exam + '\n후속 질문: ' + question if short_followup and not INTENT.search(question) else question)
    # Changing departments must not carry a course from the previous department.
    if short_followup and explicit and explicit != context.get('department'):
        original = re.sub(r'후속 질문:.*', '', previous_exam, flags=re.S)
        year_hint = re.search(r'20\d{2}', original)
        term_hint = re.search(r'[12]\s*학기', original)
        kind_hint = '기말고사' if '기말' in original else '중간고사'
        original = ' '.join([year_hint.group() if year_hint else '', term_hint.group() if term_hint else '', kind_hint, question])
    department = explicit or (filters or {}).get('category') or context.get('department')
    if department and department not in names:
        department = None
    debug = {'retrieval_mode': 'exam_schedule', 'status': 'clarification_required'}
    if not department:
        prompts = {'ko': '어느 학과의 중간·기말고사 시간표를 볼까요? 예: 컴퓨터공학과. 학과를 알려주시면 시험 날짜·시간·강의실을 확인해 드릴게요.',
                   'en': 'Which department’s exam timetable do you need?', 'ja': 'どの学科の試験時間割ですか？', 'zh': '您想查询哪个学科的考试安排？'}
        return {'answer': prompts[language], 'sources': [], 'debug_info': debug,
                'conversation_context': {'pending_question': original}}
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    year_match = re.search(r'20\d{2}', question) or re.search(r'20\d{2}', original)
    term_match = re.search(r'([12])\s*학기', question) or re.search(r'([12])\s*학기', original)
    year = year_match.group() if year_match else str(now.year)
    term = term_match.group(1) if term_match else ('1' if now.month < 8 else '2')
    kind_text = question if re.search(r'중간|기말', question) else original
    kind = '기말고사' if re.search(r'기말', kind_text) else '중간고사'
    with session_scope() as session:
        candidates = list(session.scalars(select(Notice).where(
            Notice.source_type == 'notice', Notice.category == department,
            Notice.title.contains('기말' if '기말' in kind else '중간')
        ).order_by(Notice.published_at.desc(), Notice.id.desc())))
        rows = [row for row in candidates if matches(row.title, row.content, row.published_at, year, term, kind)][:3]
    debug.update(department=department, year=year, term=term, status='ok')
    state = {'department': department, 'exam_question': original[-2000:]}
    if not rows:
        from .exam_calendar import evidence
        calendar = evidence(year, term, kind)
        if calendar is not None:
            from .rag_service import compose_answer
            debug.update(status='ok', coverage='university_calendar_only')
            prompt = (f'{original}\n질문 학과: {department}. {year}년 {term}학기 {kind}. '
                      '해당 학과의 세부 시험 공지는 수집 자료에서 확인되지 않았습니다. '
                      '근거에 있는 학교 공통 시험 기간을 먼저 직접 설명하세요. '
                      '그 기간이 해당 학과 또는 개별 과목의 확정 시간표라고 단정하지 마세요. '
                      '학과별 과목·시간·강의실은 아직 확인되지 않았다고 분명히 구분하고 '
                      '개별 일정을 원하면 학년과 과목을 물어보세요. 공지가 없다고 단정하지 마세요.')
            result = compose_answer(prompt, [calendar], language, debug)
            result['conversation_context'] = state
            return result
        debug['status'] = 'exam_not_collected'
        return {'answer': f'{department}의 {year}년 {term}학기 {kind} 시간표가 현재 수집된 자료에서 확인되지 않습니다. 공지가 없다는 뜻은 아니며, 자료 갱신 여부를 확인해야 합니다.',
                'sources': [], 'debug_info': debug, 'conversation_context': state}
    from .rag_service import compose_answer
    scoped = f'{original}\n확인 범위: {department}, {year}년 {term}학기 {kind}. 다른 학과·분반을 섞지 말고, 개인 과목·분반이 없으면 확인된 개요를 설명한 뒤 필요한 정보를 물어보세요.'
    scoped += ('\n질문에 직접 답하는 날짜·시간·장소를 먼저 쓰고 같은 내용을 반복하지 마세요. '
               '특정 과목 질문은 보통 3~5문장으로 답하세요. 전체 시간표 요청은 필요한 만큼 보여주세요. '
               '과목명만 같고 분반·교수가 다르면 하나로 확정하지 말고 구분해 설명하세요. '
               '명시적 수정 공지가 있으면 수정 내용을 우선하되 단순 게시 순서만으로 충돌을 해결하지 마세요. '
               '변경 가능성이 있는 일정에 최종 확정이라는 표현을 쓰지 마세요. '
               '질문에 이름이 없다면 이름순 배정 강의실 중 하나를 본인 강의실로 확정하지 마세요. '
               '신청 마감 등 묻지 않은 내용을 길게 덧붙이지 마세요.')
    from .db import Attachment
    with session_scope() as session:
        files = list(session.scalars(select(Attachment).where(Attachment.parent_id.in_([row.id for row in rows]), Attachment.status != 'removed')))
    unreadable = [f for f in files if f.status != 'ok']
    if unreadable:
        debug['unreadable_attachments'] = len(unreadable)
        scoped += '\n주의: 읽지 못했거나 일부만 읽은 첨부가 있습니다. 확인한 본문만 답하고, 미확인 시간은 추측하지 말며 첨부 추출 한계를 알려주세요.'
    result = compose_answer(scoped, [as_document(row) for row in rows], language, debug)
    result['conversation_context'] = state
    return result
