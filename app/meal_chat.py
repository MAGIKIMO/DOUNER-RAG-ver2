import re
from datetime import date, timedelta
from types import SimpleNamespace
from .meals import CAMPUS, today, month_data

MEAL = re.compile(r'식단|학식|학생식당|오늘\s*(?:밥|점심|저녁)|cafeteria|dining menu|学食|献立|食堂|食谱',re.I)


def answer_meal(question, language, context):
    pending=context.get('pending_meal')
    campus_reply=re.fullmatch(r'(?:승학|부민|구덕)(?:[·/ ](?:부민|구덕))?(?:캠퍼스)?(?:요)?[.!?\s]*',question.strip())
    followup=bool(context.get('meal_campus') and MEAL.search(context.get('last_question','')) and re.fullmatch(r'(?:그럼\s*)?(?:내일|오늘|어제|이번\s*달|다음\s*달|\d{1,2}월\s*\d{1,2}일)(?:은|는)?[?!\s]*',question.strip()))
    if not MEAL.search(question) and not (pending and campus_reply) and not followup:
        return None
    from .rag_service import compose_answer
    effective=pending if pending and campus_reply else question
    campus='2' if '승학' in question else '1' if any(x in question for x in ['부민','구덕']) else context.get('meal_campus')
    if campus not in CAMPUS:
        prompts={'ko':'어느 캠퍼스 식단을 볼까요? 승학 또는 구덕·부민을 알려 주세요.','en':'Which campus: Seunghak or Gudeok/Bumin?','ja':'どのキャンパスですか？승학、구덕、부민から教えてください。','zh':'想查看哪个校区的菜单？请选择승학或구덕·부민。'}
        return {'answer':prompts[language],'sources':[],'debug_info':{'status':'clarification_required','retrieval_mode':'meals'},'conversation_context':{'pending_meal':effective[:2000]}}
    target=today()
    monthly=bool(re.search(r'한\s*달|이번\s*달|월별|월간|달력|month|今月|月度',effective,re.I))
    try:
        exact=re.search(r'(20\d{2})-(\d{1,2})-(\d{1,2})',effective)
        md=re.search(r'(?:(\d{1,2})월\s*)?(\d{1,2})일',effective)
        month=re.search(r'(\d{1,2})월',effective)
        if exact:
            target=date(*map(int,exact.groups()))
        elif md:
            target=date(target.year,int(md.group(1) or target.month),int(md.group(2)))
        elif month:
            target=date(target.year,int(month.group(1)),1);monthly=True
        elif '내일' in effective or re.search(r'tomorrow|明日|明天',effective,re.I):target+=timedelta(days=1)
        elif '어제' in effective or re.search(r'yesterday|昨日|昨天',effective,re.I):target-=timedelta(days=1)
        elif '다음 달' in effective or '다음달' in effective:
            target=(target.replace(day=28)+timedelta(days=4)).replace(day=1);monthly=True
    except ValueError:
        return {'answer':'날짜를 확인해 주세요. 예: 9월 16일 식단','sources':[],'debug_info':{'status':'clarification_required','retrieval_mode':'meals'}}
    data=month_data(target.strftime('%Y-%m'),campus)
    state={'meal_campus':campus}
    if monthly:
        count=sum(d['status']=='published' for d in data['days'])
        answers={'ko':f"{data['month']} {CAMPUS[campus]} 식단은 현재 {count}일분이 등록되어 있습니다. 월별 식단에서 날짜별 메뉴를 볼 수 있습니다. 미등록 날짜는 메뉴를 추정하지 않습니다.",
                 'en':f"{data['month']}: menus are available for {count} days at {CAMPUS[campus]}. Open the monthly menu to see each date; unpublished dates are marked separately.",
                 'ja':f"{data['month']}、{CAMPUS[campus]}の献立は{count}日分登録されています。月別献立で各日のメニューを確認できます。未公開日は区別して表示します。",
                 'zh':f"{data['month']}，{CAMPUS[campus]}校区已登记{count}天的菜单。月度菜单中可查看每日内容，未发布日期将单独标注。"}
        return {'answer':answers[language],'sources':[],'meal_calendar':f"meals.html?month={data['month']}&campus={campus}",'debug_info':{'status':'ok','retrieval_mode':'meals'},'conversation_context':state}
    item=data['days'][target.day-1]
    if item['status']!='published':
        reason='아직 식단을 수집하지 못했습니다.' if item['status']=='not_collected' else '공식 식단표에 등록된 메뉴가 없습니다. 휴무 여부는 확인되지 않았습니다.'
        if language!='ko':
            reason={'en':'The menu has not been collected yet.' if item['status']=='not_collected' else 'The official page has no published menu. This does not establish that the cafeteria is closed.',
                    'ja':'献立は未収集、または公式ページに未登録です。休業を意味するものではありません。',
                    'zh':'菜单尚未收集或官方尚未发布。这不代表食堂休息。'}[language]
        result={'answer':f'{target.isoformat()} · {CAMPUS[campus]}\n{reason}','sources':[], 'debug_info':{'status':item['status'],'retrieval_mode':'meals'}}
    else:
        body=f"날짜: {target.isoformat()}\n캠퍼스: {CAMPUS[campus]}\n마지막 확인(UTC): {item['checked_at']}\n"
        body+='\n\n'.join(f"{m['cafeteria']} / {m['type']}\n{m['text']}" for m in item['menus'])
        body+='\n식자재 수급과 운영 상황에 따라 변경될 수 있음. 메뉴가 없는 식당의 휴무 여부는 확인되지 않음.'
        chunk=SimpleNamespace(source_id=f'{target}-{campus}',title=f'{target} {CAMPUS[campus]} 식단표',category=CAMPUS[campus],url=item['url'],published_at=None,source_type='meal',chunk_text=body)
        result=compose_answer(effective+'\n조회 날짜: '+target.isoformat(),[chunk],language,{'status':'ok','retrieval_mode':'meals'})
        if item['stale']:
            warnings={'ko':'오늘 갱신이 아직 확인되지 않아 이전에 수집한 메뉴입니다.','en':'Today’s refresh is not confirmed; this is a previously collected menu.','ja':'本日の更新は未確認です。以前取得した献立です。','zh':'尚未确认今天的更新，显示的是此前收集的菜单。'}
            result['answer']=warnings[language]+'\n\n'+result['answer']
    result['conversation_context']=state
    result['meal_calendar']=f"meals.html?month={data['month']}&campus={campus}"
    return result
