import io
import json
import zipfile
from types import SimpleNamespace

import pytest
import httpx
from bs4 import BeautifulSoup

from app import exam_vision, exam_tables, exam_records, attachments
from app.exam_xlsx import extract_exam_xlsx
from app.exam_context import compact_exam_files
from app.exam_fallback import readable_schedule


def record(**changes):
    row=dict(course='반응공학',date='2026-10-22',start='12:00',end='13:15',section='01',
             room='S06-0225',professor='',notes='',time_basis='explicit',location='표 행 7')
    row.update(changes)
    return row


def test_combined_date_time_not_confused_with_time_range():
    rows=exam_tables.records([(1,['교과목명','분반','시험 일시 (시간)','장소']),
                             (2,['토질역학I','02','10.22.(목) 09:00-10:15','S12-0302'])],'PDF 1쪽')
    assert len(rows)==1 and rows[0]['date']=='10-22' and rows[0]['end']=='10:15'


@pytest.mark.parametrize('changes',[{'date':'2026-02-30'},{'start':'25:00'},{'end':'11:59'},
                                     {'start':'12:60'},{'course':''},{'date':'언젠가'}])
def test_invalid_fields_are_not_published(changes):
    assert exam_records.validate(record(**changes)) is None


def merged_workbook():
    rows=[['날짜','시간','교과목명','분반','강의실','학생이름'],
          ['10.20(화)','18:00-18:50','컴퓨터구조','01','S06-0908','DO_NOT_INDEX'],
          ['','','','02','','DO_NOT_INDEX'],
          ['','','','03','S06-0921','DO_NOT_INDEX'],
          ['','','새 과목','04','','DO_NOT_INDEX']]
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="시간표" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        xml='<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        for i,row in enumerate(rows,1):
            xml+=f'<row r="{i}">'+''.join(f'<c r="{chr(65+j)}{i}" t="inlineStr"><is><t>{v}</t></is></c>' for j,v in enumerate(row))+'</row>'
        xml+='</sheetData><mergeCells>'+''.join(f'<mergeCell ref="{r}"/>' for r in ['A2:A4','B2:B4','C2:C4','E2:E3'])+'</mergeCells></worksheet>'
        z.writestr('xl/worksheets/sheet1.xml',xml)
    return out.getvalue()


def test_real_merged_ranges_preserve_section_rooms_without_blank_forward_fill():
    pages=extract_exam_xlsx(merged_workbook())
    rows=[r for p in pages for r in exam_records.decode(p['text'])]
    assert [(r['section'],r['room']) for r in rows]==[('01','S06-0908'),('02','S06-0908'),('03','S06-0921')]
    assert all(r['date']=='10-20' and r['start']=='18:00' for r in rows)
    assert 'DO_NOT_INDEX' not in json.dumps(pages) and '새 과목' not in json.dumps(pages,ensure_ascii=False)


def test_pdf_merged_bounds_only():
    # A genuinely merged course cell spans 2 rows. The second room is empty,
    # but NOT merged: it must remain empty.
    matrix=[['교과목명','분반','장소'],['토질역학','01','A'],[None,'02','']]
    geometry=[[(0,0,10,10),(10,0,20,10),(20,0,30,10)],
              [(0,10,10,30),(10,10,20,20),(20,10,30,20)],
              [None,(10,20,20,30),(20,20,30,30)]]
    table=SimpleNamespace(extract=lambda:matrix,cells=[c for row in geometry for c in row if c],
                          rows=[SimpleNamespace(cells=row) for row in geometry])
    result=exam_tables.pdf_matrix(table)
    assert result[-1][1]==['토질역학','02','']


def test_public_inline_image_discovery_excludes_navigation_and_external_hosts():
    soup=BeautifulSoup('<nav><img src="/attach/nav.png"></nav><div id="boardContents"><img src="/attach/a.PNG"><img src="https://evil.example/attach/b.png"><img src="/icons/logo.png"></div>','html.parser')
    assert list(attachments.discover(soup,'https://ee.donga.ac.kr/notice'))==['https://ee.donga.ac.kr/attach/a.PNG']


def test_vision_disagreement_is_excluded_and_partial_is_explicit(monkeypatch):
    monkeypatch.setattr(exam_vision,'image_bytes',lambda b:b)
    def request(blob,reverse=False):
        return {'is_exam_table':True,'complete':True,'warnings':[],
                'records':[record(),record(course='물리학',room='ROOM_B' if reverse else 'ROOM_A')]}
    monkeypatch.setattr(exam_vision,'request_table',request)
    page=exam_vision.extract_image(b'image')
    assert page['status']=='partial' and page['accepted_rows']==1
    assert exam_records.decode(page['text'])[0]['course']=='반응공학'
    assert '물리학' not in page['text']


def test_vision_no_exam_and_invalid_rows_do_not_enter_evidence(monkeypatch):
    monkeypatch.setattr(exam_vision,'image_bytes',lambda b:b)
    monkeypatch.setattr(exam_vision,'request_table',lambda *a,**k:{'is_exam_table':False,'records':[]})
    assert not exam_vision.extract_image(b'image')['text']
    monkeypatch.setattr(exam_vision,'request_table',lambda *a,**k:{'is_exam_table':True,'complete':True,'records':[record(start='99:00')]})
    assert exam_vision.extract_image(b'image')['status']=='review_required'


def item(content,number=1):
    row=SimpleNamespace(id=number,source='학과',source_type='attachment',category='화학공학과',
                        title='시험 안내',url='https://dache.donga.ac.kr/a.png',content=content,published_at=None,crawled_at=None)
    page=SimpleNamespace(page_number=number)
    attachment=SimpleNamespace(id='a',filename='시험.png',url=row.url,status='partial',checked_at=None)
    return row,page,attachment


def test_question_selects_correct_record_before_context_budget():
    rows=[record(course=f'다른과목{i}',section='01') for i in range(100)]
    rows.extend([record(section='01'),record(section='02',room='S06-0226')])
    docs=compact_exam_files([item(exam_records.encode(rows))],'화학공학과 반응공학 02분반 중간고사',budget=1200)
    assert len(docs)==1 and 'S06-0226' in docs[0].chunk_text
    assert 'S06-0225' not in docs[0].chunk_text and '다른과목' not in docs[0].chunk_text
    assert len(docs[0].chunk_text)<=1200
    missing=compact_exam_files([item(exam_records.encode(rows))],'반응공학 09분반 중간고사')
    assert '다른 분반 시간으로 대신 답하지' in missing[0].chunk_text


def test_grid_time_basis_is_preserved_in_fallback():
    line=exam_records.formatted([record(time_basis='grid')])[0]
    text=readable_schedule(line)
    assert 'S06-0225' in text and '격자 배치 범위' in text and '12:00~13:15' in text


def test_generation_failure_keeps_readable_normalized_schedule(monkeypatch):
    from app import rag_service, document_context
    docs = compact_exam_files([item(exam_records.encode([record()]))], '반응공학 01분반 중간고사')
    monkeypatch.setattr(document_context, 'with_attachments', lambda chunks, *a, **k: chunks)
    def unavailable(*args, **kwargs):
        raise rag_service.LLMError('provider_unavailable')
    monkeypatch.setattr(rag_service, 'grounded_answer', unavailable)
    result = rag_service.compose_answer('반응공학 01분반 중간고사', docs, 'ko', {'retrieval_mode': 'exam_schedule'})
    assert result['debug_info']['status'] == 'source_excerpt'
    assert all(value in result['answer'] for value in ('반응공학', '2026-10-22', '12:00~13:15', 'S06-0225'))
    assert len(result['sources']) == 1
    assert 'source_excerpts' not in result


def test_room_section_normalization_preserves_allocation_and_rejects_conflicts():
    row=exam_vision.canonical(record(course='반응공학I(CHE304)',section='01,02',room='S06-0225(01)'))
    assert row['course']=='반응공학I' and row['section']=='01' and row['room']=='S06-0225'
    assert exam_vision.canonical(record(section='01',room='S06-0225(02)')) is None


def test_roman_course_levels_are_not_merged():
    rows=[record(course='반응공학I'),record(course='반응공학II')]
    chosen,_=exam_records.select(rows,'반응공학Ⅰ 01분반')
    assert [r['course'] for r in chosen]==['반응공학I']
    chosen,_=exam_records.select(rows,'반응공학 01분반')
    assert len(chosen)==2  # Unqualified question retains both instead of guessing.


def test_optional_professor_disagreement_does_not_invent_professor(monkeypatch):
    monkeypatch.setattr(exam_vision,'image_bytes',lambda b:b)
    monkeypatch.setattr(exam_vision,'request_table',lambda blob,reverse=False:{'is_exam_table':True,'complete':True,'warnings':[],
        'records':[record(professor='다른 판독' if reverse else '처음 판독')]})
    page=exam_vision.extract_image(b'')
    assert page['status']=='partial'
    assert exam_records.decode(page['text'])[0]['professor']==''


@pytest.mark.parametrize('status,expected_calls',[(503,2),(401,1),(429,1)])
def test_vision_transient_retry_and_credentials_not_in_body(monkeypatch,status,expected_calls):
    monkeypatch.setenv('GEMINI_API_KEY','synthetic-secret')
    monkeypatch.setenv('GEMINI_MODEL','gemini-3.6-flash')
    monkeypatch.setenv('EXAM_VISION_ENABLED','true')
    monkeypatch.setattr(exam_vision,'image_parts',lambda blob:[])
    calls=[]
    original=httpx.Client
    def handler(request):
        calls.append(request)
        assert request.url.host=='generativelanguage.googleapis.com'
        assert 'synthetic-secret' not in str(request.url) and b'synthetic-secret' not in request.content
        assert request.headers['x-goog-api-key']=='synthetic-secret'
        payload=json.loads(request.content)
        assert payload['generationConfig']['thinkingConfig']=={'thinkingLevel':'low'}
        return httpx.Response(status,text='upstream private detail')
    monkeypatch.setattr(exam_vision.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(ValueError,match='vision_http_'+str(status)):
        exam_vision.request_table(b'public image')
    assert len(calls)==expected_calls
