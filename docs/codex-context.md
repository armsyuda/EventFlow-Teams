# EventFlow Teams 작업 연속성

## 2026-08-25 독립 GitHub 배포 및 Windows 설치

- 최신 Teams V2 실행본을 이 독립 저장소로 옮기고, `armsyuda/EventFlow-Teams` GitHub Release를 자동 업데이트 원본으로 지정했다. 초기 공개 버전은 `v0.3.49`이며 업데이트 파일은 `EventFlowTeams-Windows.zip`, 실행 파일은 `EventFlowTeams.exe`로 고정한다.
- v0.3.50부터 설치된 Teams V2는 로그인 전 실행 직후 최신 Release를 확인한다. 더 새 버전이면 검증 ZIP을 내려받아 업데이트 로딩 화면을 보여 주고, 종료·교체·재시작한다. Teams 전용 `--update-health-file` 인수를 추가해 새 실행본이 정상 창을 표시한 뒤에만 교체 성공으로 인정하며, 실패하면 기존 프로그램 폴더를 복구한다.
- Inno Setup 설치 프로그램은 관리자 권한 없이 `%LOCALAPPDATA%\Programs\EventFlow Teams`에 설치한다. Windows 앱 목록에서 제거할 수 있으며, 제거는 프로그램 폴더만 지우고 로그인 정보·작업 데이터가 있는 `%LOCALAPPDATA%\EventFlowTeams`는 보존한다.
- 설치 완료 시 `.eventflow-teams-installed` 마커를 만든다. 앱 내 업데이트는 GitHub Release SHA-256 digest를 확인하고, 교체·재기동 실패 시 기존 프로그램 폴더를 복구한다.
- GitHub Actions `Windows release`는 `v*` 태그에서 테스트·PyInstaller·Inno Setup·업데이트 ZIP·SHA256SUMS·GitHub Release를 수행한다. 실행 전 Repository Variables `EVENTFLOW_SUPABASE_URL`, `EVENTFLOW_SUPABASE_PUBLISHABLE_KEY`가 필요하다. 값은 source control에 저장하지 않는다.
- 검증: Pytest 156건, compileall, Inno 설치 파일 생성, 별도 테스트 폴더에서 설치 0/실행 유지/제거 0/프로그램 폴더 삭제를 확인했다. 배포본은 아직 코드 서명되지 않았으므로 공식 배포 전 조직 인증서 서명이 남은 보안 작업이다.

## 2026-08-25 회사 코드

- 회사 관리 화면에 OWNER/ADMIN 전용 `회사 코드 복사`를 추가했다. 서버가 발급한 고정 5자리 영문·숫자 혼합 코드를 비동기로 받아 클립보드에 복사한다.
- 이 코드는 일반 직원의 가입 신청용이며, 코드를 알아도 자동으로 회사 권한이 생기지 않는다. 프로젝트 게스트는 계속 별도의 1회성 초대 링크를 쓴다.
- 설치 파일과 GitHub Release는 사용자가 명시적으로 요청할 때만 생성한다.
- 회사 선택 화면에는 항상 `회사 목록 다시 확인`을 둔다. 직원 가입 승인 뒤에는 앱을 종료하거나 다시 로그인하지 않고 이 버튼으로 회사 소속을 다시 조회한다.
