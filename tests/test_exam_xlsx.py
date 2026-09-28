import io
import zipfile
import pytest
from bs4 import BeautifulSoup
from app.exam_xlsx import extract_exam_xlsx
from app.attachments import discover


def workbook(header='강의명'):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="시간표" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        rows = [[header,'요일','시험 시작시간','시험 종료시간'], ['컴퓨터네트워크','10/20(화)','0.6875','0.7291666666666666']]
        xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        for i, row in enumerate(rows, 1):
            xml += f'<row r="{i}">' + ''.join(f'<c r="{chr(65+j)}{i}" t="inlineStr"><is><t>{v}</t></is></c>' for j,v in enumerate(row)) + '</row>'
        z.writestr('xl/worksheets/sheet1.xml', xml + '</sheetData></worksheet>')
    return out.getvalue()


def test_time_conversion_and_source_row():
    rows = extract_exam_xlsx(workbook())
    assert len(rows) == 1
    assert '16:30' in rows[0]['text'] and '17:30' in rows[0]['text']
    assert '원본 행 2' in rows[0]['text']


def test_non_schedule_sheet_not_indexed():
    with pytest.raises(ValueError, match='headers not found'):
        extract_exam_xlsx(workbook('학생명'))


def test_actual_attachment_container():
    soup = BeautifulSoup('<div class="bdAttachFiles"><a href="/downloadRun.do?qcode=x">시험.xlsx</a></div>', 'html.parser')
    assert len(discover(soup, 'https://computer.donga.ac.kr/')) == 1
