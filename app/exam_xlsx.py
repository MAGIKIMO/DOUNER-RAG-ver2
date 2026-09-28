"""Read the public exam table only; never index student rosters or arbitrary sheets."""
import io
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
ALLOWED = {'요일', '강의명', '학과/분반', '분반 or 합반', '교수', '시험 시작시간',
           '시험 종료시간', '강의실1', '강의실2', '강의실3', '강의실4', '오픈북 여부'}
REQUIRED = {'요일', '강의명', '시험 시작시간', '시험 종료시간'}


def extract_exam_xlsx(blob):
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
                    if REQUIRED <= set(values.values()):
                        headers = {c: v for c, v in values.items() if v in ALLOWED}
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
