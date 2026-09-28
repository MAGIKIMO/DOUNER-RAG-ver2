# 검증 기록

작성일: 2026-09-14. 실제로 실행한 검사와 추가 실행이 필요한 항목을 구분합니다.

## 통과한 항목

- Python 코드 구문 검사 (`compileall`), JavaScript 구문 검사 (`node --check`).
- 로컬 정적 서버에서 `/chat.html` HTTP 200 확인. 이것은 육안 UI 검증과 구분합니다.
- Docker Compose 설정 검사: `docker compose --env-file .env.example config --no-env-resolution --quiet`. 검사에만 임시 비밀번호 문자열을 프로세스 환경으로 전달했으며 `.env` 또는 저장소에 저장하지 않았습니다.
- `tests/test_pipeline.py` 회귀 테스트 19개 통과. SQLite 메모리 DB와 HTTP/Chroma test doubles를 사용했습니다.
  - HTML 메뉴 제거, 표 행 보존, 오류 페이지 거부, 공지 상세 제목 선택, URL 정규화
  - 400자 청크/50자 중첩, 동일 문서 재수집 및 metadata 변경 감지
  - 변경 없는 벡터의 embedding 생략, 삭제된 벡터 정리, 실패 후 재색인 재시도
  - 원문 갱신 직후 오래된 vector 결과 제외
  - quota·키 누락·timeout·미지원 provider·기타 실패 시 sources 보존
  - Gemini/OpenAI/Groq 응답 파싱 및 HTTP 429 처리
  - 빈 검색 결과와 검색 서비스 장애 구분, 질문 길이/언어 검증, 관리자 인증
- FastAPI 0.115.12 / SQLAlchemy 2.0.40 / BeautifulSoup 4.13.4 / HTTPX 0.28.1로 재검사해 19개 통과(36.64초). 테스트 런타임은 Windows Python 3.13 및 pytest 9.1.1이며, Docker 목표 환경(Python 3.11, pytest 8.3.5, 전체 설치 의존성)과 동일하지 않습니다. 로컬 Starlette에서 HTTP 422 상수 deprecation 경고 2개가 발생했습니다.
- 실제 동아대학교 HTML로 파서 확인:
  - 졸업기준 안내: 정제 본문 11,398자, 스킵네비게이션 문구 없음
  - 컴퓨터공학과와 국제교류처: 각 목록 10개 링크 추출
  - 컴퓨터공학과 실제 공지 상세: 제목과 본문 1,066자 추출
  - 새 일반/학사/장학 주소: Fetcher의 robots 확인을 포함해 각각 목록 20/20/16개 링크 추출

목록 개수는 검사 시점 페이지의 결과이며 DB 저장 개수 또는 지속적인 수집 성공을 의미하지 않습니다. 대학의 실제 공지 본문 복사본은 배포물에 포함하지 않았습니다.

## 미검증 또는 제한

- 로컬 Docker CLI는 있었으나 Linux Docker 엔진이 실행 중이 아니어서 이미지 build, `pip check`, 실제 MySQL/Chroma 기동, Nginx `nginx -t`, 전체 Compose integration은 실행하지 못했습니다.
- 실제 sentence-transformers 모델 다운로드/CPU embedding 및 언어별 검색 품질은 이 환경에서 검증하지 않았습니다. 고정한 Hugging Face revision의 존재는 HTTP 200으로 확인했습니다.
- 실제 Gemini/OpenAI/Groq API 키가 제공되지 않아 외부 생성 API 호출은 하지 않았습니다. provider 테스트는 mock HTTP 응답입니다.
- 브라우저 도구의 webview 연결 시간이 초과되어 데스크톱/모바일 육안 검증을 완료하지 못했습니다. CSS 반응형과 화면 코드는 포함되어 있으나 시각 검증 통과로 간주하지 않습니다.
- GCP VM 배포 및 메모리 사용량 측정은 수행하지 않았습니다. RAM 안내는 초기 용량 계획이며 실측값이 아닙니다.

## Ubuntu에서 최종 확인할 순서

1. `.env.example`을 `.env`로 복사하고 DB 비밀번호·관리 토큰·Gemini 키를 설정합니다.
2. `docker compose up -d --build`, `docker compose ps`, `docker compose exec app pip check`, `docker compose exec web nginx -t`를 실행합니다.
3. README의 CLI 순서로 정적/게시판 수집 → chunk → vector ingest를 실행합니다.
4. `/heartbeat`의 index 상태와 `/debug/sources`, `/debug/chunks` 개수를 확인합니다.
5. `/ask`를 4개 언어로 호출하고 원문 대비 조건·기간·인용 정확도를 확인합니다.
6. 키 누락 상황에서 fallback과 sources를 확인합니다.
7. 동일 수집/ingest를 반복해 unchanged가 증가하고 불필요한 embedding이 생기지 않는지 확인합니다.
8. 브라우저에서 Enter/한글 IME/언어 선택/원문 링크/모바일 폭/로딩/네트워크 오류를 확인합니다.

실제 운영 전 이 절차를 통과해야 하며, mock 테스트 결과만으로 배포 준비 완료라고 판단하지 않습니다.
