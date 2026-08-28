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

## 2026-08-25 승인 대기 및 권한 강제 갱신

- 회사 코드 직원 가입은 `PENDING` 소속을 함께 만든다. Teams 목록에는 회사가 보이지만, 승인 전에는 전용 승인 대기 화면만 열리고 업무 데이터·로컬 작업본은 열지 않는다.
- OWNER/ADMIN은 회사 관리의 가입 요청 확인에서 직원 요청을 승인 또는 반려하고, 승인 시 기본 일반 직원 또는 선택 역할을 부여한다.
- 상단 동기화 상태 옆 `↻`는 서버 회사 목록·소속·권한·전체 작업본을 강제로 다시 확인한다. 미전송 로컬 변경이 있으면 덮어쓰지 않는다.
- 사용자 전용 Realtime 신호는 가입 승인·역할·상태·세부 권한 변경 후 같은 강제 갱신을 실행한다. 설치 파일·릴리스는 생성하지 않는다.

## 2026-08-28 권한 저장·직원 새로고침·검토 실행 파일

- 회사 관리의 직원 권한 화면은 변경 내용을 즉시 저장하지 않는다. `저장 전 변경사항` 상태와 명시적 `변경사항 저장` 버튼을 제공하며, 역할·상태·세부 메뉴 권한을 `teams_v2_save_company_member_access` 단일 서버 트랜잭션으로 저장한다. 대상 직원에게는 권한 변경 알림을 적재하고, 본인 전용 access signal 수신 시 새 권한을 다시 받아 앱 화면을 새로 연다.
- 일반 직원(MEMBER) 역할에 `events.create`를 부여해 대시보드의 `+ 새 행사`를 사용할 수 있게 했다. 직원업무에는 `직원 목록 새로고침`을 추가해 새 가입 직원 카드가 즉시 다시 내려받아 표시된다.
- 회사 선택은 회사 이름 버튼 하나를 누르면 바로 시작하도록 단순화했고, 로그아웃은 구분선 아래에 배치했다. 모든 사용자 표시 `회사 공통`은 `프로젝트 외`로 바꿨다.
- 검증: Teams Pytest 38건, Python compileall, 공백 검사, live 서버 함수/일반직원 행사 생성 권한 확인, 검토 EXE 7초 기동 검사를 통과했다. 검토 EXE는 `C:\Work\02\_EventFlow-web\desktop\teams-v2\release\EventFlowTeamsV2\EventFlowTeamsV2.exe`에만 만들었으며 GitHub Release·자동 업데이트는 아직 수행하지 않았다.

## 2026-08-28 검토 EXE QtCore 기동 오류 수정

- 검토 EXE가 일반 사용자 환경에서 `QtCore`를 불러오지 못하던 원인은 PyInstaller가 개발 환경 PATH의 호환되지 않는 ICU DLL을 포함하거나 Windows ICU bridge 일부를 누락한 것이었다.
- `build_windows.ps1`은 이제 PySide6 DLL 경로를 먼저 등록하는 runtime hook을 포함하고, 빌드 후 Windows System32의 `icu.dll`, `icuin.dll`, `icuuc.dll`을 앱의 private runtime에 명시적으로 복사한다. 다음 clean build를 위해 복사본의 읽기 전용 특성도 해제한다.
- 검토 파일을 기존 경로의 `EventFlowTeamsV2.exe`로 교체했다. System32만 남긴 격리 PATH와 별도 LOCALAPPDATA로 9초 기동을 확인했으며, 세 ICU DLL hash가 Windows System32 원본과 일치한다. GitHub Release·자동 업데이트는 계속 보류 상태다.

## 2026-08-28 v0.3.60 정식 배포

- 사용자 승인 후 커밋 `270ced8`과 태그 `v0.3.60`을 공개했다. GitHub Actions Windows release 실행 `33146356966`이 테스트, Inno 설치 파일, 자동 업데이트 ZIP, SHA-256 목록 생성 및 GitHub Release 게시를 모두 성공했다.
- 공개 Release에는 `EventFlowTeams-Setup.exe`, 버전 설치 파일, `EventFlowTeams-Windows.zip`, `SHA256SUMS.txt`가 있다. Teams 앱의 최신 Release 조회는 `0.3.60`과 자동 업데이트 ZIP을 정상 인식했다. 이미 설치된 앱은 다음 실행 시 새 버전을 알리고, 업데이트를 누르면 다운로드·검증·교체·재시작한다.

## 2026-08-28 TLS 인증서 경로 수정

- 일부 PC의 기존 `REQUESTS_CA_BUNDLE` 환경값이 삭제된 사용자 폴더를 가리켜 회사 목록 조회가 실패했다. PyInstaller runtime hook이 앱에 포함된 `certifi/cacert.pem`을 `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `SSL_CERT_FILE`에 명시적으로 설정하도록 수정했다.
- 오래된 외부 인증서 경로를 넣은 패키지 실행 환경 시뮬레이션에서 앱 내부 인증서 파일로 교체되는 것을 확인했다. 38개 Teams 테스트와 compileall도 통과했다. 다음 공개 버전은 `0.3.61`이다.
