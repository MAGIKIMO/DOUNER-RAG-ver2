"""Explicit student reports; no automatic conversation logging."""
import json
import threading
import time
from collections import defaultdict
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, DateTime
from . import db


class Feedback(db.Base):
    __tablename__='answer_feedback'
    id=Column(Integer,primary_key=True)
    question=Column(Text,nullable=False)
    answer=Column(Text,nullable=False)
    reason=Column(String(30),nullable=False)
    comment=Column(Text,nullable=False)
    sources=Column(Text,nullable=False)
    created_at=Column(DateTime,nullable=False,default=db.utcnow)


class Source(BaseModel):
    title:str=Field(max_length=1000)
    url:str=Field(max_length=2000)


class Report(BaseModel):
    client_id:UUID
    question:str=Field(min_length=1,max_length=2000)
    answer:str=Field(min_length=1,max_length=8000)
    reason:Literal['wrong_answer','outdated','wrong_source','missing_detail','other']
    comment:str=Field(default='',max_length=1000)
    sources:list[Source]=Field(default_factory=list,max_length=20)


router=APIRouter()
_attempts=defaultdict(list)
_lock=threading.Lock()


def check_limit(key):
    now=time.monotonic()
    with _lock:
        for old in list(_attempts):
            _attempts[old]=[t for t in _attempts[old] if now-t<3600]
            if not _attempts[old]:del _attempts[old]
        if len(_attempts.get(key,[]))>=10:
            raise HTTPException(429,'신고 요청이 많습니다. 잠시 후 다시 시도해 주세요.')
        _attempts[key].append(now)


@router.post('/api/v1/feedback',status_code=201)
def submit_report(report:Report,request:Request):
    check_limit(str(report.client_id))
    with db.session_scope() as session:
        row=Feedback(question=report.question,answer=report.answer,reason=report.reason,
                     comment=report.comment,sources=json.dumps([s.model_dump() for s in report.sources],ensure_ascii=False))
        session.add(row);session.flush()
        return {'id':row.id,'status':'received'}
