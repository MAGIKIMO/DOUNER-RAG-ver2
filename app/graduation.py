"""Collect student scope before looking up graduation rules. No hardcoded credits."""
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select, or_
from .db import Notice, session_scope


def prepare(question, category=None, context=None, language="ko"):
    context = dict(context or {})
    intent = bool(re.search(r"졸업.*(학점|요건|조건|가능|하려|할|몇)|graduat.*(credit|require|eligib)|卒業.*(単位|要件|条件)|毕业.*(学分|条件|要求)",question,re.I))
    if not intent and not context.get("pending_question"):
        return None, None
    # Explicit new topic leaves the graduation clarification flow.
    if not intent and re.search(r"최근|최신|장학|기숙사|휴학|latest|scholarship",question,re.I):
        return None, None
    try:
        catalog=json.loads(Path(__file__).with_name("public_sources.json").read_text(encoding="utf-8"))
        names={d["name"] for d in catalog.get("departments",[])}
    except (OSError, ValueError):
        names=set()
    names.update({"컴퓨터공학과","AI학과"})
    matches=sorted((n for n in names if n in question),key=len,reverse=True)
    department=matches[0] if matches else context.get("department")
    if "컴공" in question:
        department="컴퓨터공학과"
    if not department and category in names:
        department=category
    year=context.get("admission_year")
    match=re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)",question)
    short=re.search(r"(?<!\d)(\d{2})\s*학번",question)
    if match:
        year=int(match.group(1))
    elif short:
        value=int(short.group(1));year=2000+value if value <= date.today().year%100 else 1900+value
    if year and not 1970 <= year <= date.today().year:
        year=None
    state={"pending_question":context.get("pending_question") or question,"department":department,"admission_year":year}
    if not department or not year:
        missing="both" if not department and not year else "department" if not department else "year"
        prompts={
            "ko":{"both":"어느 학과이고, 몇 년도에 입학하셨나요? 예: 컴퓨터공학과 2022학번. 졸업학점과 이수 조건은 학과·입학연도에 맞는 기준으로 확인하겠습니다.","department":"어느 학과인가요? 학과명을 알려주시면 해당 입학연도의 졸업기준을 확인하겠습니다.","year":f"{department}의 몇 년도 입학생인가요? 예: 2022학번. 적용되는 졸업학점 기준을 확인하는 데 필요합니다."},
            "en":{"both":"What is your department and admission year? For example: 컴퓨터공학과, 2022. Graduation requirements depend on both.","department":"What is your department? Please use its official Korean name or select it above.","year":"In which year did you enter the university?"},
            "ja":{"both":"学科名と入学年度を教えてください。例：컴퓨터공학과、2022年。","department":"学科名を教えてください。上の選択欄もご利用いただけます。","year":"入学年度を教えてください。"},
            "zh":{"both":"请告诉我您的学科和入学年份。例如：컴퓨터공학과，2022年。","department":"请告诉我学科名称，也可以使用上方选择框。","year":"请问您的入学年份是哪一年？"},
        }
        return state,{"answer":prompts[language][missing],"sources":[],"debug_info":{"status":"clarification_required","intent":"graduation"},"conversation_context":state}
    return state,None


def rule_text(row, admission_year=None):
    text = row.content
    # The curriculum page holds many cohorts. Keep the complete matching section,
    # rather than spending context on newer cohorts or cutting off the older one.
    if admission_year and parse_qs(urlsplit(row.url).query).get("mCode") == ["MN117"]:
        headings = list(re.finditer(r"(?m)^((?:19|20)\d{2})학년도 신입생부터 적용되는 교과과정\s*$", text))
        for index, heading in enumerate(headings):
            if int(heading.group(1)) == admission_year:
                end = headings[index+1].start() if index+1 < len(headings) else len(text)
                return text[heading.start():end].strip()
    return text[:50000]


def evidence(department, admission_year=None):
    """Retrieve full rule tables rather than loosely related notice chunks."""
    with session_scope() as session:
        rows=list(session.scalars(select(Notice).where(Notice.source_type != 'attachment', or_(
            Notice.title.contains("졸업기준"),Notice.title.contains("졸업요건"),
            Notice.title.contains("졸업학점"),Notice.title.contains("교과과정"),
            Notice.title.contains("교육과정"),Notice.title.contains("이수학점"),
            Notice.url.contains("mCode=MN137"),Notice.url.contains("mCode=MN117")
        )).order_by(Notice.published_at.desc(),Notice.id.desc())))
    common=[]; specific=[]
    for row in rows:
        parsed=urlsplit(row.url)
        is_common=(parsed.hostname in {"www.donga.ac.kr","donga.ac.kr"}
                   and parsed.path.startswith("/kor/") and row.source_type=="static")
        if row.category==department:
            specific.append(row)
        elif is_common:
            common.append(row)
    common.sort(key=lambda r:parse_qs(urlsplit(r.url).query).get("mCode") != ["MN137"])
    selected=common[:2]+specific[:2]
    return [SimpleNamespace(source_id=r.id,source_type=r.source_type,category=r.category,title=r.title,url=r.url,
                            published_at=r.published_at,chunk_text=rule_text(r, admission_year)) for r in selected]
