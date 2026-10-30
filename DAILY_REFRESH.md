# 매일 최신 공지와 중간고사 자료 갱신

최초 코드 반영 후 앱을 한 번 빌드합니다. 일일 작업은 재빌드하지 않습니다.

```powershell
docker compose up -d --build app
```

지금 중간고사 공지만 갱신하려면:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\refresh-notices.ps1 -ExamsOnly
```

전체 공지 게시판까지 갱신하려면 `-ExamsOnly`를 빼면 됩니다.
기본 최근 30일, 게시판당 최대 10페이지이며 정적 학교 소개 등은 매일 다시 수집하지 않습니다.
시험 갱신은 해당 학기 중간고사 공지와 첨부를 처리하고 텍스트 분할·벡터 갱신까지 수행합니다.
같은 URL/동일 내용·파일은 기존 해시 비교를 사용합니다. 확인을 위한 HTTP 다운로드는 발생합니다.
기말고사 수집은 별도로 `app.update_exams --kind 기말고사`를 실행할 수 있습니다.

매일 오전 7시(Windows 로컬 시간)에 등록:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\register-daily-refresh.ps1
```

작업 이름은 `Douner-Daily-Refresh`입니다. 등록을 다시 실행하면 같은 이름의 작업을 갱신합니다.
PC에 로그인되어 있고 Docker Desktop과 app 컨테이너가 실행 중이어야 합니다.
놓친 예약은 실행 가능한 시점에 시작하도록 설정하지만 PC가 꺼진 동안 실행되는 서비스는 아닙니다.
프로세스 실패는 15분 간격으로 최대 3회 재시도합니다. 개별 게시판/미지원 첨부의 부분 실패는
전체 재실행하지 않고 다음 일일 실행 때 다시 시도하므로 로그를 반드시 확인해야 합니다.

로그: 프로젝트의 `logs/refresh-날짜-시간.log`. 새 시험 공지별 `created`, `updated`, `unchanged`와
학과별 `exam_coverage`가 출력됩니다. 파이프라인 완료가 모든 자료 추출 성공을 뜻하지 않습니다.
동시 실행은 스크립트 파일 잠금과 기존 MySQL 유지보수 잠금으로 방지합니다.

상태 확인 / 중지:

```powershell
Get-ScheduledTaskInfo -TaskName Douner-Daily-Refresh
Disable-ScheduledTask -TaskName Douner-Daily-Refresh
```

작업 등록·실제 Docker 갱신 성공 여부는 실행 후 확인해야 합니다.
