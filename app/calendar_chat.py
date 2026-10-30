"""Answer common calendar dates from verified rows without a generation API."""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
from .exam_calendar import record

# Keys select source rows; labels are translations, never date constants.
EVENTS = {
    'final': (r'기말\s*(?:고사|시험)?|final\s*(?:exam(?:ination)?s?)?|期末(?:試験|考试|考試)', r'기말(?:시험|고사)',
              ('기말시험', 'final exams', '期末試験', '期末考试')),
    'midterm': (r'중간\s*(?:고사|시험)|midterm(?:\s*exams?)?|中間試験|期中(?:考试|考試)', r'중간(?:시험|고사)',
                ('중간시험', 'midterm exams', '中間試験', '期中考试')),
    'registration': (r'수강\s*신청|course registration|履修登録|选课|選課', r'수강신청',
                     ('수강신청', 'course registration', '履修登録', '选课')),
    'tuition': (r'등록금|tuition|学費|学费|등록\s*기간', r'제[12]학기등록$',
                ('등록', 'tuition registration', '学費納付', '学费缴纳')),
    'start': (r'개강|classes begin|semester start|start of (?:the )?semester|開講|开学|開學', r'개강',
              ('개강', 'start of classes', '開講', '开学')),
    'vacation': (r'방학|vacation|summer break|winter break|夏休み|冬休み|寒假|暑假', r'(하계|동계)방학',
                 ('방학', 'vacation', '休暇', '假期')),
    'makeup': (r'보강|make.?up (?:day|class)|補講|补课|補課', r'보강일',
               ('보강일', 'make-up class days', '補講日', '补课日')),
    'grade_release': (r'성적\s*(?:공시|공개|조회|정정|발표)|성적\s*언제\s*나|grade (?:release|publication|correction)|成績(?:公開|訂正)|成绩(?:公布|更正)', r'성적공시|성적정정',
                      ('성적공시 및 정정', 'grade publication and correction', '成績公開・訂正', '成绩公布及更正')),
    'grade_entry': (r'성적\s*입력|grade entry|成績入力|成绩录入', r'성적입력',
                    ('성적입력', 'grade entry', '成績入力', '成绩录入')),
    'grade_final': (r'성적\s*확정|grade finalization|成績確定|成绩确定', r'성적확정',
                    ('성적확정', 'grade finalization', '成績確定', '成绩确定')),
    'graduation': (r'학위\s*수여식|졸업식|commencement|graduation ceremony|学位授与式|毕业典礼', r'학위수여식',
                   ('학위수여식', 'degree ceremony', '学位授与式', '毕业典礼')),
    'anniversary': (r'개교\s*기념일|university anniversary|開校記念日|校庆', r'개교기념일',
                    ('개교기념일', 'university anniversary', '開校記念日', '校庆')),
    'labor': (r'근로자의\s*날|labor day|labour day|労働者の日|劳动节', r'근로자의날',
              ('근로자의 날', 'Labor Day', '労働者の日', '劳动节')),
}
LANGS = ('ko', 'en', 'ja', 'zh')


def period(value):
    """Resolve abbreviated source date ranges; discard invalid/reversed dates."""
    parts = re.split(r'[~～–]', value)
    dates = []
    try:
        for part in parts:
            nums = [int(n) for n in re.findall(r'\d+', part)]
            if len(nums) == 3:
                at = date(*nums)
            elif len(nums) == 2 and dates:
                at = date(dates[0].year, *nums)
            else:
                return None
            dates.append(at)
    except ValueError:
        return None
    return dates if 1 <= len(dates) <= 2 and dates[-1] >= dates[0] else None


def rows(content):
    year = None
    result = []
    for line in content.splitlines():
        heading = re.search(r'(20\d{2})\s*학년도\s*학사일정', line)
        if heading:
            year = int(heading[1])
        cells = [c.strip() for c in line.split('|')]
        if not year or len(cells) != 3 or not re.fullmatch(r'[12]\s*학기', cells[0]):
            continue
        # Old tables put dates before the event; the new site reverses them.
        dates = period(cells[1])
        event = cells[2]
        if dates is None:
            dates, event = period(cells[2]), cells[1]
        if dates:
            result.append({'year': year, 'term': int(cells[0][0]), 'event': event, 'dates': dates})
    return result


def intent(question, context=None):
    context = context or {}
    previous = context.get('calendar_question') if context.get('last_route') != 'chat' else None
    followup = bool(previous and re.fullmatch(
        r'\s*(?:그럼\s*)?(?:(?:20\d{2})\s*(?:년|학년도)?\s*)?(?:[12]\s*학기)?\s*(?:은|는|도)?[?？.! ]*', question))
    query = previous + '\n' + question if followup else question
    if previous and re.match(r'\s*그럼', question) and any(re.search(p, question, re.I) for p, _, _ in EVENTS.values()):
        # New event, same academic scope; do not carry the previous event itself.
        scope = ' '.join(re.findall(r'20\d{2}년|[12]학기', previous))
        query, followup = scope + ' ' + question, True
    events = [key for key, (pattern, _, _) in EVENTS.items() if re.search(pattern, query, re.I)]
    all_events = bool(re.search(r'학사\s*일정|academic calendar|学事暦|学事日程|校历|校曆', query, re.I))
    if not events and not all_events:
        return None
    # Procedures, eligibility and personal/course schedules still use RAG.
    if re.search(r'어떻게|방법|자격|서류|준비|학점|얼마|공부|힘들|싫|걱정|망했|분반|강의실|교수|내\s*시간표|'
                 r'학과|학부|전공|컴공|department|professor|classroom|section|how to|学科|教室|课程|課程', question, re.I):
        return None
    if re.search(r'수강\s*(?:신청\s*)?(?:정정|취소)|계절\s*학기|휴학|복학|재입학|신입생|대학원', question):
        return None
    if not followup and not all_events and not re.search(
        r'언제|기간|일정|날짜|몇\s*월|며칠|시작|끝|when|dates?|period|schedule|いつ|期間|日程|什么时候|何时|日期|时间', query, re.I):
        return None
    if any(k in events for k in ('final', 'midterm')) and not all_events:
        # Unknown course names must not be mistaken for a school-wide exam.
        residual = query
        for pattern, _, _ in EVENTS.values():
            residual = re.sub(pattern, '', residual, flags=re.I)
        residual = re.sub(r'20\d{2}\s*(?:학년도|년도|년|年度|学年度|学年|年)?|(?:第\s*)?[12一二]\s*(?:학기|学期)', '', residual)
        residual = re.sub(r'동아대학교|동아대|공식|공통|학교|전체|학사|이번|올해|내년|작년|그럼|'
                          r'알려\s*주세요|알려\s*줘|알려조|언제|기간|일정|날짜|몇\s*월|며칠|시작|끝|'
                          r'확정|정확한|부터|까지|인가요|예요|에요|임|야|좀|은|는|이|가|요|의|을|를|에', '', residual)
        residual = re.sub(r'\buniversity[\s-]+wide\b|\bacademic\s+year\b', '', residual, flags=re.I)
        residual = re.sub(r'\b(?:when|what|are|is|the|for|at|in|of|donga|dong|a|university|'
                          r'first|second|spring|fall|autumn|semester|dates?|period|schedule|please|tell|me|this|year)\b',
                          '', residual, flags=re.I)
        residual = re.sub(r'東亜大学|东亚大学|期末|中間|試験|考试|考試|期間|日程|いつ|ですか|は|の|'
                          r'什么时候|何时|日期|时间|第[一二12]学期|[12]学期|年|的|是', '', residual)
        if re.search(r'[A-Za-z가-힣一-龥ぁ-んァ-ン]', residual):
            return None
    return events, query, followup


def answer_calendar(question, language='ko', context=None, now=None):
    found = intent(question, context)
    if found is None:
        return None
    events, query, followup = found
    now = now or datetime.now(ZoneInfo('Asia/Seoul'))
    years = re.findall(r'(?<!\d)(20\d{2})(?!\d)', query)
    year = int(years[-1]) if years else now.year
    if '내년' in question:
        year = now.year + 1
    elif '작년' in question:
        year = now.year - 1
    terms = re.findall(r'([12一二])\s*(?:학기|学期)', query)
    if terms:
        term = {'1': 1, '2': 2, '一': 1, '二': 2}[terms[-1]]
    elif re.search(r'여름|하계|summer|夏休み|暑假|spring|first semester', query, re.I):
        term = 1
    elif re.search(r'겨울|동계|winter|冬休み|寒假|fall|autumn|second semester', query, re.I):
        term = 2
    else:
        # An explicit year without a semester gets both semesters.
        term = None if years or re.search(r'올해|내년|작년', query) else (1 if 3 <= now.month < 8 else 2)
        if not years and not re.search(r'올해|내년|작년', query) and now.month < 3:
            year -= 1
    if re.search(r'다음\s*학기|next semester', question, re.I) and not years:
        current_term = 1 if 3 <= now.month < 8 else 2
        academic_year = now.year - (now.month < 3)
        term, year = (2, academic_year) if current_term == 1 else (1, academic_year + 1)
    language = language if language in LANGS else 'ko'
    li = LANGS.index(language)
    scope = (f'{year}학년도' + (f' {term}학기' if term else ''),
             f'Academic year {year}' + (f', semester {term}' if term else ''),
             f'{year}年度' + (f' 第{term}学期' if term else ''),
             f'{year}学年' + (f' 第{term}学期' if term else ''))[li]
    source = record()
    selected = [r for r in rows(source.content) if r['year'] == year and (term is None or r['term'] == term)
                and (not events or any(re.search(EVENTS[k][1], re.sub(r'\s+', '', r['event'])) for k in events))] if source else []
    canonical = f'{year}년 ' + (f'{term}학기 ' if term else '') + ' '.join(EVENTS[k][2][0] for k in events)
    if not events:
        canonical += ' 학사일정'
    result = {'sources': [], 'conversation_context': {'calendar_question': canonical},
              'debug_info': {'retrieval_mode': 'academic_calendar', 'status': 'ok', 'year': year, 'term': term}}
    if not selected:
        result['debug_info']['status'] = 'calendar_not_collected'
        result['answer'] = (
            f'{scope}의 요청한 공식 일정이 수집된 학사일정에서 확인되지 않습니다. 자료 갱신이 필요할 수 있으며 다른 연도 일정으로 대신 답하지 않겠습니다.',
            f'The requested dates for {scope} are not available in the collected official calendar. A refresh may be needed; dates from another year cannot substitute for them.',
            f'{scope}の該当日程は収集済みの公式学事暦で確認できません。資料の更新が必要な場合があります。',
            f'已收集的官方校历中未确认{scope}的相关安排，可能需要更新资料。')[li]
        return result
    lines = []
    for row in selected:
        kind = next((k for k, (_, pattern, _) in EVENTS.items() if re.search(pattern, re.sub(r'\s+', '', row['event']))), None)
        label = row['event'] if language == 'ko' or kind is None else EVENTS[kind][2][li]
        dates = ' ~ '.join(at.isoformat() for at in row['dates'])
        semester = (f"{row['term']}학기", f"Semester {row['term']}", f"第{row['term']}学期", f"第{row['term']}学期")[li]
        lines.append(f'• {semester} {label}: {dates} [1]')
    intro = (f'{scope} 학교 공통 학사일정입니다.', f'Official university-wide calendar for {scope}.',
             f'{scope}の大学共通日程です。', f'以下是{scope}的全校统一日程。')[li]
    note = ('과목별 시험 날짜·시간·강의실은 학과 및 담당 교수 공지와 다를 수 있어 별도로 확인해야 합니다.',
            'Individual course exam dates, times and rooms require the department or instructor notice.',
            '科目別の試験日時・教室は学科や担当教員のお知らせを確認してください。',
            '各课程的考试日期、时间及教室需另行核对院系或任课教师通知。')[li]
    result['answer'] = intro + '\n' + '\n'.join(lines)
    if any(re.search(r'중간|기말', r['event']) for r in selected):
        result['answer'] += '\n\n' + note
    result['sources'] = [{'id': 1, 'title': source.title, 'category': source.category, 'url': source.url,
                          'source_type': source.source_type, 'source_id': source.id,
                          'published_at': source.published_at.isoformat() if source.published_at else None,
                          'checked_at': source.crawled_at.isoformat()+'Z' if source.crawled_at else None}]
    return result
