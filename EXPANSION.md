# 공개 정보 수집 확장 — 2026-09-14

## 목표와 현재 범위

LMS를 제외하고 전체 학과의 공개 공지와 본교 메뉴의 공개 안내를 수집하는 확장입니다. 공식 대학 디렉터리에서 학과 주소를 발견하고 실제 홈페이지 메뉴에서 게시판을 찾아 `app/public_sources.json`에 저장했습니다. 추측한 mCode를 넣지 않았습니다.

**주소 발견, 본문 수집, DB 저장, 벡터 색인, 답변 품질 검증은 서로 다른 단계입니다.** 이번 변경에 주소 목록과 수집/검색 코드가 포함됩니다. 전체 최근 1년 corpus를 실제 MySQL에 수집 완료한 상태는 아닙니다. Docker 엔진 접근이 제한되어 로컬 Docker 명령은 사용자가 실행해야 합니다.

디렉터리에서 발견한 68개 항목 중 64개에서 지원 CMS 공지 메뉴를 발견했습니다. 여기에는 학과 외 학부·전공·영문 페이지가 있으므로 '동아대 학과 총수 68개'라는 의미가 아닙니다.

추가 대응 항목:

| 항목 | 이유 |
|---|---|
| 환경·에너지공학부 미래에너지공학전공 | 공식 디렉터리가 외부 도메인 donga.dsso.kr을 연결함. 현재 donga.ac.kr 수집 범위 밖 |
| 글로벌비즈니스학과(영문) | 현재 탐색 규칙에서 지원 게시판을 찾지 못함 |
| 자유전공학부 | 디렉터리에 학과 홈페이지 주소 미표기 |
| 융합전공 | 디렉터리에 홈페이지 주소 미표기 |

본교 학교소개·입학안내·대학·대학원·학사안내·대학생활·동아광장·80주년 메뉴를 함께 조사했습니다. 표준 CMS Contents/Board는 수집하고, 별도 서비스의 홈페이지·ASP·커스텀 목록은 `adapter_required`로 남깁니다. 입학처·도서관·교내연락처·캠퍼스맵 등까지 전부 수집 완료했다고 보아서는 안 됩니다. PDF/HWP/OCR와 로그인 서비스도 미지원입니다.

## 저장 구조

- 기존 notices/context_chunks/Chroma 흐름 유지. 기존 테이블을 삭제하거나 변경하지 않습니다.
- 새 `public_sources` 테이블만 추가합니다. 주소·학과·분류·수집 상태·조회 페이지 수·이번 실행 저장/갱신 건수·오류·마지막 시도를 관리합니다.
- 학과 자료의 category는 공식 학과명, 공통 자료의 category는 본교 메뉴 분류입니다. 기존 벡터 metadata에도 category가 있으므로 같은 구조로 필터링합니다.
- 공지 본문·게시일·원문 URL은 기존 notices에 저장하고 기존 content_hash로 수정분을 감지합니다.
- 날짜 없는 공지, 이미지 위주 공지, 본문 추출 실패는 실패 로그에 남깁니다. 고정 페이지는 최근 1년 제한 없이 저장합니다.
- 공지 페이지 순회는 고정 공지를 제외한 게시일이 내림차순이고 전부 기준일 이전일 때 날짜 경계로 중단합니다. 이때 **게시판의 날짜 정렬을 전제로 하는 수집 범위**입니다. 전체 역사적 게시물을 무조건 조회한 것은 아닙니다.
- max-pages에 도달하거나 페이지가 반복되면 partial이며, 자료가 조금 저장됐더라도 전체 완료로 처리하지 않습니다.
- `documents_saved`는 이번 실행에서 정상 저장/재확인한 건수입니다. URL 중복을 포함한 전체 DB 문서 수나 신규 문서 수와 다릅니다.

## 사용자가 실행할 명령 — PowerShell

실제 프로젝트에서 코드 적용 후 실행합니다. 기존 .env, docker-compose.yml의 포트와 data 폴더는 유지합니다.

```powershell
cd C:\Users\ljh21\Downloads\donga-rag-v2
docker compose up -d --build app
docker compose exec app python -m app.crawl_public --days 365 --max-pages 200
```

수집이 끝난 뒤:

```powershell
docker compose exec app python -m app.ingest_notices_to_context
docker compose exec app python -m app.ingest_context_to_chroma
```

수집은 많은 사이트를 순차 방문하므로 오래 걸릴 수 있습니다. 1초 간격을 기본으로 하며 요청을 무제한 병렬화하지 않습니다. 완료 전 기존 질문 서비스는 기존 corpus로 동작합니다. 수집 중 수정된 원문은 재색인 전 기존 stale vector가 제외됩니다.

실패/부분 완료 출처만 다시 시도:

```powershell
docker compose exec app python -m app.crawl_public --days 365 --max-pages 500 --retry-only
```

신규 공지 갱신은 `--retry-only` 없이 실행해야 성공한 게시판도 다시 방문합니다. 자동 일일 예약은 이번 변경에서 설정하지 않았습니다. 먼저 수집시간과 실패율을 확인하고 스케줄을 정하세요.

공식 메뉴 주소를 다시 탐색하고 그 결과로 수집:

```powershell
docker compose exec app python -m app.public_catalog --output /tmp/donga-public-sources.json
docker compose exec app python -m app.crawl_public --catalog /tmp/donga-public-sources.json --days 365 --max-pages 200
```

`/tmp` 목록은 컨테이너 재생성 때 사라질 수 있습니다. 계속 사용할 새 목록은 `docker cp`로 로컬에 보관한 뒤 app/public_sources.json을 갱신하여 재빌드하세요. 발견하지 못한 출처를 기존 DB에서 자동 삭제하지 않습니다.

## 검색 변경

- 화면의 '학과·자료 범위'에서 수집된 category를 선택할 수 있습니다. 선택하면 해당 category로 엄격히 필터링합니다. 해당 학과 자료가 부족해도 다른 학과로 자동 확대하지 않습니다.
- 질문에 DB category 이름이 정확히 하나 포함되면 그 category를 자동 적용합니다. 별칭/줄임말/다국어 학과명은 자동 식별하지 못하므로 선택기를 사용하세요.
- 전체 자료를 선택한 일반 의미 검색은 서로 다른 학과의 자료도 검색합니다. 입학연도나 학과별 eligibility를 자동 판별하는 기능까지 구현한 것은 아닙니다.
- '최신 공지 목록'은 벡터 유사도 대신 **MySQL 게시일 내림차순**으로 최근 1년 공지 5개를 반환합니다. 일부 '최근 공지' 표현도 자동 전환됩니다.
- 최신 목록의 안내문은 4개 언어이며 공지 제목은 원문 그대로 표시합니다. LLM 요약을 호출하지 않으므로 quota가 없어도 목록이 동작합니다.
- `GET /api/v1/categories`: 공개 분류와 저장 문서 수.
- `GET /api/v1/debug/coverage`: 관리자 키가 필요한 출처별 수집 상태.
- `POST /api/v1/ask` 추가 입력: `category`(선택), `search_mode`=`auto|semantic|latest`.

학과 졸업요건과 공통 졸업규정의 다중 근거를 결합하는 기능, 적용 연도 정규화, 첨부파일 근거 연결은 다음 단계입니다.

## 검증과 품질 목표

기존 19개 + 확장 6개 = 회귀 테스트 25개 통과. 새로운 테스트는 공개 URL 경계, URL 중복, 학과 경로 분리, 수집 상태 보존, 게시일 정렬·학과 필터, 수집 오류를 검증합니다. SQLite와 test doubles를 사용하는 테스트이며 실제 MySQL 전체 수집·Chroma 재색인 검증은 별도입니다.

'GPT보다 잘 답한다'는 것은 이 프로젝트의 검증 목표로 두어야 하며 지금 달성했다고 보장할 수 없습니다. 다음 질문셋을 원문 정답과 함께 만들어 비교하세요.

1. 학과별 최신 공지를 정확한 날짜·URL과 함께 찾는가?
2. 졸업/장학 조건을 학과·입학연도·신청기간별로 구분하는가?
3. 원문에 없는 질문을 추측하지 않고 모른다고 답하는가?
4. 답변의 각 숫자/기한이 인용 문서에 실제로 존재하는가?
5. 한국어·일본어·영어·중국어 질문에서 같은 근거를 찾는가?

발견 출처 수 대비 수집 성공률, 최신성, Recall@5, 인용 정확도, 답변 거부 정확도, 응답 지연을 측정하면 개선 효과를 설명할 수 있습니다. 수집량만 늘려서는 이 품질이 보장되지 않습니다.

공식 출처: [동아대학교 메인](https://www.donga.ac.kr/kor/Main.do), [대학·학과 디렉터리](https://www.donga.ac.kr/kor/CMS/Contents/Contents.do?mCode=MN272).
