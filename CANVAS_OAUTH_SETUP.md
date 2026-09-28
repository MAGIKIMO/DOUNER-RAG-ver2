# Canvas OAuth 가입·로그인 준비

학교 Canvas에서 로그인·동의하면 Canvas 사용자 ID를 기준으로 서비스 계정을 생성합니다. 별도 이메일/비밀번호 회원가입은 이번 범위에 포함하지 않습니다. 학교 비밀번호·학번을 우리 화면에서 받지 않습니다. 개인정보를 입력하는 토큰 폼도 없습니다.

현재 기본값은 비활성입니다. 학교 관리자가 승인한 Developer Key의 Client ID/Secret과 고정 HTTPS 주소를 설정해야 실제 연결됩니다. 개인 CLI의 `CANVAS_API_TOKEN`은 웹에서 사용하지 않습니다.

## 학교 관리자에게 요청할 내용

- 용도: 동아대학교 학생 대상 졸업프로젝트의 본인 수강 과목·공지·과제 안내.
- 인증: Canvas API OAuth2 authorization code 방식의 Developer Key (LTI 키가 아님).
- Redirect URI: `https://서비스도메인/api/v1/canvas/callback` (실제 고정 HTTPS 도메인으로 교체).
- 최소 읽기 scope:
  - `url:GET|/api/v1/users/:user_id/profile`
  - `url:GET|/api/v1/courses`
  - `url:GET|/api/v1/announcements`
  - `url:GET|/api/v1/courses/:course_id/assignments`
- 수집/저장: 계정 식별자, 암호화한 OAuth 토큰, 해시한 로그인 세션. 공지·과제는 요청 시 읽고 공용 MySQL notices/Chroma에 저장하지 않음.
- 외부 AI: 학생이 동의하고 질문을 전송할 때 선택한 과목의 공지·과제·제출 상태 일부와 질문을 설정된 LLM 제공자에게 전송함.
- 쓰기 작업: 과제 제출·수정·성적 변경 없음. 연결 해제 시 OAuth 토큰 폐기 요청만 수행.

기관의 허용 여부는 확인되지 않았습니다. OAuth 클라이언트 등록을 이 코드가 대신하거나 관리자 권한을 우회하지 않습니다.

## 설정 및 실행

현재 `.env`는 자동 수정하지 않았습니다. 아래를 추가하되 기존 `CANVAS_BASE_URL`이 있으면 중복 작성하지 마세요.

```dotenv
CANVAS_OAUTH_ENABLED=true
CANVAS_BASE_URL=https://canvas.donga.ac.kr
APP_PUBLIC_ORIGIN=https://실제서비스도메인
CANVAS_CLIENT_ID=학교에서받은값
CANVAS_CLIENT_SECRET=학교에서받은값
CANVAS_TOKEN_ENCRYPTION_KEY=직접생성한키
```

키와 비밀번호를 GitHub나 채팅에 붙여 넣지 마세요. 먼저 새 코드를 빌드합니다.

```powershell
docker compose up -d --build app
docker compose exec -T app python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

출력된 암호화 키를 `.env`에 저장하고 안전하게 별도 보관합니다. 임의 재생성하면 기존 토큰을 읽을 수 없습니다. 실제 Client Secret도 `.env`에 입력한 후:

```powershell
docker compose up -d --no-deps --force-recreate app
docker compose restart web
```

`.ps1` 실행이 필요하지 않습니다. TLS 리버스 프록시에서 기존 8080 웹으로 연결하고, 외부 프록시/터널의 callback 로그에도 code/state 쿼리가 저장되지 않게 설정하세요. OAuth에는 주소가 바뀌는 임시 터널보다 고정 주소를 사용하세요. 기존 DB에 새 테이블만 생성하며 볼륨을 지우지 않습니다.

## 화면과 동작

`/account.html`에서 Canvas로 가입·로그인 → 과목 선택 → AI 전송 동의 → 질문을 실행합니다. 학교 승인 전 PC의 `http://localhost:8080/account.html`에서는 준비 중 화면만 확인할 수 있습니다. HTTPS Secure 쿠키를 사용하므로 실제 인증을 HTTP로 테스트하지 않습니다.

- 세션은 최대 7일, OAuth 요청은 10분 후 만료됩니다. state는 브라우저 쿠키와 결합되고 한 번만 사용할 수 있습니다.
- 토큰은 계정 식별자와 결합해 암호화하며, 세션은 해시만 저장합니다. 토큰 갱신은 MySQL 행 잠금으로 직렬화합니다.
- API는 로그인 세션에서 사용자 ID를 결정합니다. 요청자가 임의 account_id를 지정할 수 없습니다.
- 로그아웃은 현재 세션만 삭제합니다. 다시 로그인하면 이전 세션은 무효화합니다.
- 연결 해제는 모든 세션과 서비스 Canvas 계정·토큰을 삭제합니다. 원격 토큰 폐기에 실패하면 Canvas 설정에서도 승인된 통합을 해제하라는 안내를 표시합니다.
- 개인 질문/답변은 채팅 기록, notices, Chroma, localStorage, 서비스 워커에 저장하지 않습니다. API에 `Cache-Control: no-store`를 적용합니다.
- Nginx access 로그에서 쿼리를 제외하고 callback 로깅을 끕니다. Uvicorn access 로그도 끕니다.

## 현재 범위와 검증 한계

수강 과목과 선택한 한 과목의 최근 30일 공지·과제 내용에 답합니다. 주간 강의 시간표, 강의 첨부파일, LearningX 출결/동영상 진도, 전체 과목 통합 개인 벡터 검색, 프로필/관심 공지 서버 동기화는 포함하지 않습니다.

OAuth 성공/실패, state 재사용·만료·다른 브라우저 차단, 사용자 자료 분리, 암호화, 토큰 갱신, 로그아웃·연결 해제는 모의 Canvas 응답과 SQLite로 검사합니다. 학교의 실제 Client ID/Secret이 없으므로 실제 OAuth 로그인·학교별 scope 승인은 검증하지 못했습니다. 운영 MySQL과 휴대폰 화면은 배포 후 추가 확인이 필요합니다.

공식 문서: https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth
