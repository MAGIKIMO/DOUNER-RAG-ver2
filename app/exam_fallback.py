"""Evidence-only output when the model is unavailable; never invent a schedule."""
import re

def readable_schedule(line):
    if not re.match(r'^\[(?:PDF|정규화) 일정 \d+\]', line): return line
    fields = dict(part.strip().split(': ',1) for part in re.sub(r'^\[(?:PDF|정규화) 일정 \d+\]\s*','',line).split('|') if ': ' in part.strip())
    return ('• ' + fields.get('강의명','') + '\n  ' + fields.get('시험일','') + ' · ' + fields.get('시간','')
            + ' · ' + fields.get('분반','') + '\n  ' + fields.get('강의실','') + ' ' + fields.get('안내','')
            + (' · '+fields['시간 근거'] if fields.get('시간 근거') else ''))


def excerpt_answer(context, language, error_code=None):
    intros = {
        'ko': 'AI 설명 생성에 실패해, 수집된 시험 자료의 원문을 표시합니다. 아래는 개인별 확정 일정이 아니며 수정 공지와 본인 분반을 함께 확인해야 합니다.',
        'en': 'AI generation is unavailable. Below are excerpts in the original source language. Check amendments and your section; these are not a confirmed personal schedule.',
        'ja': 'AI応答を生成できないため、収集した試験資料を原文で表示します。変更通知とご自身のクラスを確認してください。個人の確定日程ではありません。',
        'zh': 'AI暂时无法生成回答，以下显示已收集考试资料的原文。请核对变更通知和本人班次，这不是已确认的个人考试安排。',
    }
    excerpts = []
    remaining = 3000
    for doc in context:
        lines = doc['text'].splitlines()
        selected = [line for line in lines if re.match(r'^\[(?:원본 행|PDF 일정|정규화 일정) \d+\]', line)]
        if '학교 공통 학사일정' in doc['text']:
            selected = [line for line in lines if '|' in line and re.search(r'중간시험|기말시험', line)]
        if not selected and re.search(r'(?m)^\[원본 \d+쪽\]', doc['text']):
            # Preserve PDF page text as an excerpt, without fabricating table
            # columns or selecting a student's room from flattened cells.
            selected = [part.strip() for part in re.split(r'(?m)(?=^\[원본 \d+쪽\])', doc['text'])
                        if re.match(r'^\[원본 \d+쪽\]', part)]
        if not selected:
            continue
        chosen = []
        truncated = False
        for line in selected[:5]:
            if len(line) + 160 > remaining:
                if line.startswith('[원본 ') and '쪽]' in line[:25] and remaining > 360:
                    piece = line[:remaining-160]
                    if '\n' in piece:
                        piece = piece.rsplit('\n', 1)[0]
                    chosen.append(piece)
                    remaining -= len(piece) + 160
                    truncated = True
                break
            chosen.append(readable_schedule(line))
            remaining -= len(line) + 160
        if not chosen:
            continue
        text = doc['title'] + '\n' + '\n'.join(chosen)
        if truncated or len(chosen) < len(selected) or '일부' in doc['text'] or '전체 시간표가 아니' in doc['text']:
            text += '\n[일부 발췌 / Partial excerpt]'
        if '학교 공통 학사일정' in doc['text']:
            text += '\n[학교 공통 기간 / University-wide period]'
        excerpts.append(text + f" [{doc['source']}]")
    reasons = {
        'provider_unavailable': {'ko':'답변 생성 API가 일시적인 서버 오류를 반환했습니다.', 'en':'The answer API returned a temporary server error.', 'ja':'回答生成APIで一時的なサーバーエラーが発生しました。', 'zh':'回答生成API返回了暂时性服务器错误。'},
        'quota_exceeded': {'ko':'답변 생성 API의 요청 한도에 도달했습니다.', 'en':'The answer API request limit was reached.', 'ja':'回答生成APIのリクエスト上限に達しました。', 'zh':'回答生成API已达到请求限额。'},
        'timeout': {'ko':'답변 생성 API의 응답 시간이 초과됐습니다.', 'en':'The answer API timed out.', 'ja':'回答生成APIがタイムアウトしました。', 'zh':'回答生成API响应超时。'},
    }
    reason = reasons.get(error_code, {}).get(language, '')
    if language == 'ko' and any('[PDF 일정 ' in d['text'] or '[정규화 일정 ' in d['text'] for d in context):
        intros['ko'] = 'AI 설명 생성이 원활하지 않아, 원문 표에서 확인한 일정만 정리했어요. 본인 분반과 수정 공지를 함께 확인해 주세요.'
    return (reason + '\n' if reason else '') + intros[language] + '\n\n' + '\n\n'.join(excerpts) if excerpts else None


def unstructured_message(language):
    return {
        'ko':'시험 시간표는 찾았지만 지금 AI 요약을 생성하지 못했어요. 표의 날짜·과목 연결을 확실히 확인할 수 없어 임의로 정리하지 않았습니다. 추출 원문은 아래에서 펼쳐 볼 수 있어요.',
        'en':'I found the timetable, but AI summarization is unavailable. I cannot reliably match dates to courses in this table. You can expand the extracted source text below.',
        'ja':'試験時間割は見つかりましたが、AI要約を生成できませんでした。表の日付と科目の対応を確実に確認できないため、推測で整理していません。抽出した原文は下で開けます。',
        'zh':'已找到考试时间表，但暂时无法生成AI摘要。无法可靠地对应表中的日期与科目，因此未作推测。可在下方展开提取的原文。',
    }[language]
