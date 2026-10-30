# 응답 속도와 스트리밍

- 명확한 학교 정보 질문은 잡담 분류 LLM 호출을 생략합니다. 감정 표현 등 모호한 질문은 기존 분류를 유지합니다.
- 외국어 검색용 번역 요청에서 route도 반환받아 중복 분류를 생략합니다. 번역 실패 시 기존 검색 경로로 진행합니다.
- `POST /api/v1/ask/stream`은 NDJSON 이벤트를 전송합니다. `phase`, `answer_delta`, `reset`, `result`, `error`, `ping` 이벤트가 있습니다.
- Gemini 답변 생성은 SSE를 사용합니다. 완성된 문단에 유효한 출처 번호가 있는 경우 먼저 표시하며 최종 응답으로 전체 화면을 확정합니다. 출처 번호 검사 자체는 사실성/함의 검증을 뜻하지 않습니다. 잘못된 인용·생성 실패·재시도 시 최종 결과 또는 오류로 교체합니다.
- OpenAI/Groq는 기존 응답 경로를 유지합니다. 단계 표시 후 최종 답변이 표시되며 Gemini 방식의 문단 스트리밍은 적용되지 않습니다.
- 질문/답변 캐시는 추가하지 않았습니다. API와 스트림은 서비스 워커 캐시에서 제외됩니다. 개인정보나 프롬프트는 성능 로그에 추가하지 않습니다.
- `debug_info.timings_ms`: query_preparation, classification(실행 시), retrieval(벡터 검색 시), generation, total. 재시도 시 generation은 마지막 시도 시간입니다.
- `debug_info.llm_calls`, `llm_ms`: 논리적 LLM 호출 횟수 및 누적 호출 시간. HTTP 내부 재시도 횟수와는 다릅니다.
- Nginx는 응답의 `X-Accel-Buffering: no`로 버퍼링을 끕니다. `/api/`의 기존 요청 제한을 유지합니다. 연결 종료 시 진행 중인 공급자 요청이 끝날 때까지 동시 요청 슬롯을 유지합니다.

## 적용

`docker compose up -d --build app` 후 브라우저 Ctrl+F5 또는 PWA 새 버전 안내의 새로고침을 선택합니다. 재수집·재임베딩은 필요 없습니다.

## 확인

`node tests/test_answer_stream.cjs`, `node tests/test_pwa.cjs`, Python 테스트를 실행합니다. 실제 API의 첫 문단 시간과 전체 시간은 모델·서버 부하·답변 길이에 따라 변합니다. 스트리밍만으로 전체 생성 시간이 단축된다고 보장하지 않습니다.
