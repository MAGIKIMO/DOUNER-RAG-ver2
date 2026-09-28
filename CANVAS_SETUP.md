# 본인 계정 Canvas 연결 테스트

이 버전은 터미널 전용 개인 테스트입니다. 공개 `/api/v1/ask`에는 연결하지 않습니다. 수업 자료를 공용 MySQL·Chroma에 넣거나 자동으로 파일에 저장하지 않습니다. 브라우저에 토큰을 전달하지 않습니다. 모든 Canvas 요청은 GET 조회이며 과제 제출·수정·삭제는 하지 않습니다.

## 1. 로컬 설정

Canvas 설정에서 테스트용 새 액세스 토큰을 본인이 생성하고 적절한 만료일을 지정합니다. 기존 AndroidStudent 토큰의 `protected`는 사용할 토큰 값이 아닙니다. 토큰은 채팅·스크린샷·Git에 올리지 마세요.

프로젝트 `.env`에 아래 두 항목을 추가합니다. BASE_URL은 **토큰 설정 화면 주소창의 실제 HTTPS 도메인**입니다. 포털 주소나 문서 사이트 주소를 사용하지 말고, `/profile/settings` 같은 경로도 제외하세요.

```dotenv
CANVAS_BASE_URL=https://실제-Canvas-도메인.donga.ac.kr
CANVAS_API_TOKEN=본인이_생성한_토큰
```

`.env`는 기존 `.gitignore`에서 제외됩니다. `.env.example`에는 실제 토큰을 쓰지 마세요. 환경변수는 Docker 컨테이너 설정을 볼 수 있는 로컬 운영자에게는 보일 수 있습니다. 저장하지 않으려면 토큰 항목을 비워두고 각 명령에 `--prompt-token`을 붙여 숨김 입력할 수 있습니다.

## 2. 연결과 수강 과목 확인

```powershell
docker compose up -d --build --no-deps app
docker compose exec app python -m app.canvas_lms check
docker compose exec app python -m app.canvas_lms courses
```

check가 `connected`이면 Canvas 본인 계정 API 인증에 성공한 것입니다. courses는 활성 학생 수강 과목의 ID·이름·학기를 보여줍니다. 과거 과목·비공개 과목·다른 사람의 과목은 이 테스트 범위에 포함하지 않습니다.

`.env` 토큰만 나중에 변경했다면 `docker compose up -d --no-deps --force-recreate app`으로 환경변수를 다시 반영하세요. `docker compose restart`만으로는 새 환경변수가 적용되지 않습니다.

## 3. 과목 하나의 공지와 과제 조회

아래 `12345`는 예시입니다. courses 결과의 실제 ID로 바꿔 실행합니다.

```powershell
docker compose exec app python -m app.canvas_lms course --course-id 12345
```

공지 최근 30일과 과제 목록·본문·마감일·API가 제공하는 본인 제출 상태를 반환합니다. 공지 기간은 `--days 90`처럼 바꿀 수 있습니다(최대 365일). 성적·점수·교수 피드백·다른 학생 명단은 별도로 요청하거나 결과에 포함하지 않습니다. 공지 본문에 쓰인 내용은 원문대로 표시되므로 결과를 공유할 때 개인 정보를 확인하세요.

시간은 한국 시간(+09:00)으로 변환합니다. `due_at: null`은 마감일 미확인이며 무기한을 뜻하지 않습니다. 외부 도구(LearningX 등)가 관리하는 출결·영상 진도·과제 상태가 Canvas API에 모두 노출된다고 보장할 수 없습니다. `coverage`의 실패/부분 조회 상태를 반드시 함께 봐야 합니다.

## 4. 선택한 과목 내용으로 질문

**ask 명령은 질문과 선택한 과목의 공지·과제 정보 일부를 `.env`에 설정한 LLM 제공자에게 전송합니다.** Canvas 토큰·계정 프로필은 전송하지 않습니다. 이 전송을 원할 때 실행하세요. check/courses/course 명령은 LLM을 호출하지 않습니다.

```powershell
docker compose exec app python -m app.canvas_lms ask --course-id 12345 --question "이번 주 과제 마감일과 해야 할 일을 알려줘"
```

명령 실행 시 Canvas에서 다시 조회하므로 저장된 과거 스냅샷을 최신인 것처럼 사용하지 않습니다. 질문은 한 과목 기준입니다. 공지 첨부파일 다운로드·출결 처리·자동 알림·웹 채팅 연결은 아직 포함하지 않습니다. 질문에 필요한 내용이 없어도 추측하지 않도록 근거와 조회 범위를 전달합니다. 문서량이 많으면 목록·본문 일부가 생략되며 이를 표시합니다.

## 오류 확인

- `authentication_failed`: 토큰·만료·발급 도메인 확인.
- `redirect_blocked` / `unexpected_response`: 포털 주소 대신 실제 Canvas 도메인인지 확인. 리다이렉트에 토큰을 자동 전달하지 않습니다.
- `permission_denied`: 학교·과목·토큰 권한으로 조회가 제한됨.
- `rate_limited`: 잠시 후 재시도.
- `coverage` 일부 실패: 공지/과제가 없다는 의미가 아닙니다.

실제 토큰을 받기 전에는 학교 서버 연결 성공을 확인할 수 없습니다. 배포 단계에는 학교 관리자와 OAuth 앱 등록을 협의하고, 학생별 로그인·토큰 저장·자료 접근 분리를 구현해야 합니다. 개인 토큰을 다른 학생에게 입력하도록 요구하는 서비스로 배포하지 마세요.

검증: 개인 LMS 테스트 23개를 포함한 전체 105개 테스트 통과. 실제 학교 계정 연결은 로컬 도메인·토큰 설정 후 별도로 확인해야 합니다.

공식 문서: [OAuth](https://developerdocs.instructure.com/services/canvas/oauth2/file.oauth), [과목](https://developerdocs.instructure.com/services/canvas/resources/courses), [공지](https://developerdocs.instructure.com/services/canvas/resources/announcements), [과제](https://developerdocs.instructure.com/services/canvas/resources/assignments).
