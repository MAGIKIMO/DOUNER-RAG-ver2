"""Explainable public-notice suggestions; never certify personal eligibility."""
import re
from datetime import datetime, timedelta
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from .db import Notice, session_scope
from .canvas_lms import KST

router=APIRouter(prefix='/api/v1/notices')
TOPICS={'scholarship':('장학',),'career':('취업','인턴','채용','진로'),
        'program':('비교과','프로그램','공모전','모집'), 'academic':('수강','휴학','복학','졸업','학사'),
        'international':('유학생','외국인','국제교류','교환학생')}
LABELS=dict(scholarship='장학금',career='취업·진로',program='프로그램·공모전',academic='학사',international='국제교류')


class Preferences(BaseModel):
    department: str = Field(default='',max_length=100)
    admission_year: int | None = Field(default=None,ge=1970,le=2100)
    interests: list[Literal['scholarship','career','program','academic','international']] = Field(default_factory=list,max_length=5)


def deadline(content, today):
    """Only a single unambiguous, full-year application deadline; no year guessing."""
    found=[]
    for line in content.splitlines():
        if len(line)>700 or not re.search(r'신청|접수|지원|제출',line) or not re.search(r'기간|마감|까지',line):continue
        dates=[]
        for y,m,d in re.findall(r'(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})',line):
            try:dates.append(datetime(int(y),int(m),int(d)).date())
            except ValueError:pass
        # Reject a range with an abbreviated end date instead of misreading its start as the deadline.
        if re.search(r'~|∼|부터',line) and len(dates)!=2:continue
        if len(dates)==1 and not re.search(r'마감|까지',line):continue
        if len(dates)>2 or (len(dates)==2 and (not re.search(r'~|∼|부터',line) or dates[0]>dates[1])):continue
        if dates:found.append((dates[-1],line.strip()))
    if not found or len({d for d,_ in found})!=1:
        return {'date':None,'status':'unknown','evidence':None}
    day,evidence=found[0]
    return {'date':day.isoformat(),'status':'past_date' if day<today else 'today_check_time' if day==today else 'future_date',
            'evidence':evidence,'note':'본문의 날짜 후보입니다. 정확한 마감 시각·연장 여부·지원 자격은 별도 확인하세요.'}


def rank(rows, preferences, now=None):
    now=now or datetime.now(KST).replace(tzinfo=None)
    selected=[];seen=set()
    for row in rows:
        if not row.published_at or not now-timedelta(days=90)<=row.published_at<=now:continue
        department=preferences.department.strip()
        is_department=bool(re.search(r'학과|학부|전공',row.category))
        if is_department and row.category!=department:continue
        text=row.title+'\n'+row.content
        reasons=[];score=0
        if department and row.category==department:reasons.append('선택한 학과 공지');score+=8
        for topic in dict.fromkeys(preferences.interests):
            words=TOPICS[topic]
            if any(w in text for w in words):
                reasons.append('관심 분야: '+LABELS[topic]);score+=4+sum(w in row.title for w in words)
        if not reasons:continue
        if preferences.admission_year and re.search(str(preferences.admission_year)+r'\s*(?:학년도\s*)?(?:입학|학번)',text):
            reasons.append('입학연도 관련 문구 포함 — 적용 대상 확인 필요');score+=1
        info=deadline(row.content,now.date())
        if info['status']=='past_date':continue
        key=re.sub(r'\s+','',row.title)
        if key in seen:continue
        seen.add(key)
        lines=[line.strip() for line in row.content.splitlines() if line.strip()]
        relevant=[line for line in lines if re.search(r'대상|자격|신청|접수|기간|제출|지원|선발|혜택',line)]
        excerpt='\n'.join((relevant or lines)[:6])[:1500]
        selected.append((score,row.published_at,{'id':row.id,'title':row.title,'category':row.category,'url':row.url,
            'published_at':row.published_at.isoformat(),'checked_at':row.crawled_at.isoformat()+'Z' if row.crawled_at else None,
            'reasons':reasons,'excerpt':excerpt,'deadline':info}))
    selected.sort(key=lambda x:(x[0],x[1]),reverse=True)
    return [x[2] for x in selected[:8]]


@router.post('/recommend')
def recommend(preferences: Preferences):
    now=datetime.now(KST).replace(tzinfo=None)
    if not preferences.department.strip() and not preferences.interests:
        return {'items':[],'message':'학과 또는 관심 분야를 선택해 주세요.','candidate_limit_reached':False}
    terms=[w for topic in preferences.interests for w in TOPICS[topic]]
    conditions=[Notice.category==preferences.department.strip()] if preferences.department.strip() else []
    conditions += [or_(Notice.title.contains(w,autoescape=True),Notice.content.contains(w,autoescape=True)) for w in terms]
    with session_scope() as db:
        rows=list(db.scalars(select(Notice).where(Notice.source_type=='notice',Notice.published_at>=now-timedelta(days=90),
                  Notice.published_at<=now,or_(*conditions)).order_by(Notice.published_at.desc(),Notice.id.desc()).limit(1000)))
    return {'items':rank(rows,preferences,now),'candidate_limit_reached':len(rows)==1000,
            'message':'수집된 최근 90일 공지에서 추천합니다. 추천은 지원 자격 충족이나 현재 접수 중임을 보장하지 않습니다.'}


@router.post('/{notice_id}/summary')
def summary(notice_id: int):
    from .document_context import as_document
    from .rag_service import compose_answer
    from .main import ask_slots
    if not ask_slots.acquire(blocking=False):raise HTTPException(429,'잠시 후 다시 시도해 주세요.')
    try:
        with session_scope() as db:
            row=db.get(Notice,notice_id)
            if not row or row.source_type!='notice':raise HTTPException(404,'공지를 찾지 못했습니다.')
            document=as_document(row)
        return compose_answer('이 공지의 핵심 내용, 지원 대상, 신청 기간, 제출 방법을 본문 근거로 설명해 줘. 없는 항목은 미확인이라고 말해 줘. 개인 지원 자격은 단정하지 마.',
              [document],'ko',{'status':'ok','retrieval_mode':'selected_notice'})
    finally:ask_slots.release()
