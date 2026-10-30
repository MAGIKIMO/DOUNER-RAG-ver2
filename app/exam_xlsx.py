"""Read the public exam table only; never index student rosters or arbitrary sheets."""
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
ALLOWED = {'요일', '강의명', '학과/분반', '분반 or 합반', '교수', '시험 시작시간',
           '시험 종료시간', '강의실1', '강의실2', '강의실3', '강의실4', '오픈북 여부'}
ALIASES = {'과목명': '강의명', '교과목명': '강의명', '시험일자': '요일', '시험일': '요일', '날짜': '요일',
           '시작시간': '시험 시작시간', '시작': '시험 시작시간', '종료시간': '시험 종료시간', '종료': '시험 종료시간',
           '강의실': '강의실1', '시험장소': '강의실1', '담당교수': '교수', '분반': '분반 or 합반'}
def header(value):
    normalized = re.sub(r'\s+', '', value)
    return next((v for v in ALLOWED if re.sub(r'\s+', '', v) == normalized), ALIASES.get(normalized, value))

REQUIRED = {'요일', '강의명', '시험 시작시간', '시험 종료시간'}


def _extract_fixed(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        if len(archive.infolist()) > 1000 or sum(i.file_size for i in archive.infolist()) > 40 * 1024 * 1024:
            raise ValueError('xlsx_expansion_limit')
        def xml(path):
            data = archive.read(path)
            if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
                raise ValueError('unsafe_xml')
            return ET.fromstring(data)
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(t.text or '' for t in si.findall('.//m:t', NS))
                       for si in xml('xl/sharedStrings.xml').findall('m:si', NS)]
        relations = {r.get('Id'): r.get('Target') for r in xml('xl/_rels/workbook.xml.rels')
                     if r.get('TargetMode') != 'External'}
        for sheet in xml('xl/workbook.xml').findall('m:sheets/m:sheet', NS):
            if sheet.get('state', 'visible') != 'visible':
                continue
            target = relations.get(sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'), '')
            path = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            if not path.startswith('xl/worksheets/'):
                continue
            rows = xml(path).findall('m:sheetData/m:row', NS)
            headers = None
            result = []
            for row in rows:
                values = {}
                for cell in row.findall('m:c', NS):
                    col = re.sub(r'\d', '', cell.get('r', ''))
                    value = cell.findtext('m:v', '', NS)
                    if cell.find('m:f', NS) is not None:
                        value = ''  # cached formula results may be stale
                    elif cell.get('t') == 's':
                        value = strings[int(value)]
                    elif cell.get('t') == 'inlineStr':
                        value = ''.join(t.text or '' for t in cell.findall('.//m:t', NS))
                    values[col] = value.strip()
                if headers is None:
                    labels = {c: header(v) for c, v in values.items()}
                    if REQUIRED <= set(labels.values()):
                        headers = {c: v for c, v in labels.items() if v in ALLOWED}
                    continue
                record = {label: values.get(col, '') for col, label in headers.items()}
                if not record.get('강의명'):
                    continue
                for field in ('시험 시작시간', '시험 종료시간'):
                    value = record[field]
                    if re.fullmatch(r'0?\.\d+', value):
                        minutes = round(float(value) * 24 * 60)
                        record[field] = f'{minutes // 60:02d}:{minutes % 60:02d}'
                text = f'시험 시간표 · 시트: {sheet.get("name")} · 원본 행 {row.get("r")}\n'
                text += '\n'.join(f'{k}: {v or "원문 미기재"}' for k, v in record.items())
                result.append({'page': len(result) + 1, 'text': text, 'status': 'ok', 'label': f'엑셀 시간표 행 {row.get("r")}'})
                if len(result) > 1000:
                    raise ValueError('too_many_exam_rows')
            if result:
                return result
    raise ValueError('unsupported: verified exam table headers not found')


def extract_exam_xlsx(blob):
    # Preserve the existing verified computer-engineering schema, including its
    # multiline section/room allocation notes.
    try:
        return _extract_fixed(blob)
    except ValueError as exc:
        if str(exc) != 'unsupported: verified exam table headers not found':
            raise
    from .exam_tables import records
    from .exam_records import encode
    pages=[]
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        def xml(path):
            data=archive.read(path)
            if b'<!DOCTYPE' in data or b'<!ENTITY' in data:
                raise ValueError('unsafe_xml')
            return ET.fromstring(data)
        strings=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings=[''.join(t.text or '' for t in si.findall('.//m:t',NS)) for si in xml('xl/sharedStrings.xml').findall('m:si',NS)]
        relations={r.get('Id'):r.get('Target') for r in xml('xl/_rels/workbook.xml.rels') if r.get('TargetMode')!='External'}
        def address(value):
            match=re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,5})',value)
            if not match:
                raise ValueError('invalid_cell_address')
            column=0
            for ch in match[1]: column=column*26+ord(ch)-64
            return int(match[2]),column
        for sheet in xml('xl/workbook.xml').findall('m:sheets/m:sheet',NS):
            if sheet.get('state','visible')!='visible': continue
            target=relations.get(sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'),'')
            path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            if not path.startswith('xl/worksheets/'): continue
            tree=xml(path); cells={}; hidden=set()
            for row in tree.findall('m:sheetData/m:row',NS):
                if row.get('hidden')=='1': hidden.add(int(row.get('r')))
                for cell in row.findall('m:c',NS):
                    value=cell.findtext('m:v','',NS)
                    if cell.find('m:f',NS) is not None: value=''
                    elif cell.get('t')=='s': value=strings[int(value)]
                    elif cell.get('t')=='inlineStr': value=''.join(t.text or '' for t in cell.findall('.//m:t',NS))
                    cells[address(cell.get('r',''))]=value.strip()
            expanded=0
            for merge in tree.findall('m:mergeCells/m:mergeCell',NS):
                first,last=merge.get('ref').split(':')
                r1,c1=address(first); r2,c2=address(last)
                expanded+=(r2-r1+1)*(c2-c1+1)
                if expanded>100000 or r2<r1 or c2<c1: raise ValueError('xlsx_merge_limit')
                value=cells.get((r1,c1),'')
                # Only explicit OOXML merge ranges propagate values. Blank
                # unrelated rows/cells are never forward-filled.
                for r in range(r1,r2+1):
                    for c in range(c1,c2+1):
                        if not cells.get((r,c)): cells[(r,c)]=value
            if not cells: continue
            last_col=max(c for r,c in cells)
            rows=sorted(set(r for r,c in cells)-hidden)
            if last_col>200 or len(rows)*last_col>200000: raise ValueError('xlsx_table_limit')
            matrix=[(r,[cells.get((r,c),'') for c in range(1,last_col+1)]) for r in rows]
            for record in records(matrix,f'엑셀 시트 {sheet.get("name")}'):
                number=record['location'].rsplit(' ',1)[-1]
                text=f'시험 시간표 · 시트: {sheet.get("name")} · 원본 행 {number}\n강의명: {record["course"]}\n'+encode([record])
                pages.append({'page':len(pages)+1,'text':text,'status':'ok','label':f'엑셀 시간표 행 {number}'})
                if len(pages)>1000: raise ValueError('too_many_exam_rows')
    if not pages: raise ValueError('unsupported: verified exam table headers not found')
    return pages
