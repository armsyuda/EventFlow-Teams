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
- `v0.3.61`은 공개 배포되었고, GitHub Actions 실행 `33146777901`이 설치 파일·자동 업데이트 ZIP·SHA-256 목록 게시까지 성공했다. 최신 Release 조회도 `0.3.60` 설치본에서 업데이트 대상으로 정상 인식한다.

## 2026-08-28 자동 업데이트 복구 원인 및 수정

- `0.3.60`과 `0.3.61`의 현장 업데이트 로그는 파일 교체와 새 EXE 실행까지 성공했으나, 새 Teams entry point가 `--update-health-file` 인수를 처리하지 않아 30초 뒤 복구 경로가 실행된 것을 기록했다.
- Teams V2 entry point가 이제 인수를 읽고, 실제 Teams 창이 정상 생성된 뒤에만 health 파일에 `ok`를 기록한다. 설정 오류 창인 경우에는 기록하지 않아 정상적인 롤백 안전장치는 유지된다.
- 패키지 EXE를 오래된 인증서 환경값과 격리 사용자 데이터 환경에서 `--update-health-file`로 실행해 health 파일 `ok` 생성을 확인했다. Teams 테스트 39건과 compileall을 통과했으며 다음 배포 버전은 `0.3.62`이다.

## 2026-08-28 빈 프로젝트 생성·표시 용어 검토본

- 프로젝트 생성 화면은 기본 항목 선택을 선택 사항으로 바꿨다. 빈 프로젝트를 만든 뒤 체크리스트의 `직접 항목 추가`로 첫 업무를 등록할 수 있으며, local outbox도 빈 `tasks` 배열을 가진 `EVENT_CREATE_WITH_TASKS` 요청을 만들도록 보완했다.
- 화면·입력 검증·PDF·Excel의 일반 표시 문구는 `행사` 대신 `프로젝트`로 통일했다. 기존 기본 항목의 대분류 값 `행사`와 `행사보험`처럼 사용자 데이터로 쓰이는 실제 항목명은 변경하지 않는다.
- 운영 서버에 `teams_allow_empty_project_creation` 마이그레이션을 적용했다. private 생성 helper는 빈 tasks 배열을 허용하고, 기존 `events.create` 권한 검사와 같은 조직 참조 검사는 그대로 유지한다.
- 검증: 관련 자동 검사 152건과 Python compileall을 통과했다. 검토 EXE는 `C:\Work\02_EventFlow-web\desktop\teams-v2\release\EventFlowTeamsV2\EventFlowTeamsV2.exe`에 생성했고, 별도 LOCALAPPDATA 환경에서 10초 기동 및 update-health-file `ok` 기록을 확인했다. 운영 서버 함수에서 빈 프로젝트 허용과 authenticated mutation 실행 권한을 확인했다. GitHub Release·자동 업데이트는 수행하지 않았다.

## 2026-08-28 빈 프로젝트 예산 미입력 서버 보정

- 실제 빈 프로젝트 재시도에서 로컬의 빈 예산 세금 구분값 `UNSET`가 서버 `events_budget_tax_mode_check` 제약에 전달되어 거부되는 것을 확인했다. `teams_normalize_project_budget_tax_mode` 운영 마이그레이션은 `INCLUDED`/`EXCLUDED`만 저장하고, `UNSET`·빈 값은 `NULL`로 정규화한다.
- JMT 소유자 권한의 실제 mutation을 트랜잭션 안에서 빈 tasks와 `UNSET`로 실행해 `APPLIED`, `budget=NULL`, `budget_tax_mode=NULL`을 확인한 뒤 롤백했다. 기존 빈 프로젝트 `1234`의 거부된 로컬 outbox 요청은 `PENDING`으로 되돌렸으며, 다음 앱 실행 및 로그인 후 자동 재시도된다.
- 이번 서버 보정은 검토본의 동기화 오류 수정이며, GitHub Release·자동 업데이트는 사용자 승인 전까지 수행하지 않는다.

## 2026-08-28 빈 프로젝트 기본 항목·업무 동기화 보정

- 빈 프로젝트 생성 화면은 기본 항목을 선택 사항으로 표시했지만 최초 체크 상태가 전체 선택으로 남아 있던 결함이 있었다. 이제 기본 항목은 모두 해제된 상태로 시작하고, `전체 선택`을 명시적으로 누른 항목만 프로젝트에 복사된다. 이전 프로젝트에서 가져오기 화면의 기존 전체 선택 동작은 유지한다.
- 서버의 `TASK_CREATE` 경로는 `event_tasks` 복합 반환값을 단일 UUID처럼 받으려 해 기본 항목 전송이 거부되고 있었다. `teams_fix_task_create_mutation` 마이그레이션은 올바른 행 선택으로 보정하고, 프로젝트 수정에서 `UNSET` 예산 VAT 값도 `NULL`로 정규화한다. JMT OWNER 권한의 트랜잭션 검증에서 직접 항목 생성이 `APPLIED`를 반환했고, 롤백 뒤 서버 프로젝트 업무 수는 0건이었다.
- 사용자가 만든 프로젝트 `12312331`에 잘못 생성된 서버 기본 업무 120개와 로컬 기본 업무·실패/대기 outbox 244개를 제거했다. 로컬 작업본의 cursor를 비워 다음 실행 시 서버 snapshot을 새로 받게 했으며, 프로젝트 자체는 빈 상태로 보존했다.
- 새 검토 EXE를 `C:\Work\02\_EventFlow-web\desktop\teams-v2\release\EventFlowTeamsV2\EventFlowTeamsV2.exe`와 호환 검토 경로에 같은 hash로 복사했다. 10초 격리 기동과 update health `ok`를 확인했다. GitHub Release·자동 업데이트는 여전히 사용자 승인 전 보류한다.

## 2026-08-28 공용 날짜 입력 달력·직원 색상 고정 검토본

- 모든 날짜 입력이 쓰는 `DirectDateEdit` 팝업을 보정했다. 현재 달 밖의 날짜는 `#BAC1CC`(흰 배경에서 약 30% 농도)로 표시하고, 현재 달로 이동하면 기본 색으로 되돌린다. 달력 높이를 280px, 팝업 높이를 336px로 늘려 여섯 번째 주가 잘리지 않게 했고, 화면 하단·우측에서는 팝업 위치를 화면 안으로 조정한다.
- 나의 공간의 20색 선택 버튼과 색상 저장 호출을 제거했다. 색상은 서버의 20색 고정 팔레트에서 가입/ACTIVE 전환 시 사용하지 않은 색을 우선 무작위 배정하며, 모두 사용된 뒤에는 사용 빈도가 가장 낮은 색부터 재사용한다. 새 로컬 작업본의 임시 기본색도 이 팔레트의 `#A7D4F0`로 통일했다.
- 검증 중 달력·직원 화면 관련 Pytest 20건과 Python compileall, 공백 검사를 통과했다. 전체 171건 중 6건은 이번 변경과 무관하게 기존 Local용 업데이트 테스트가 오래된 `EventFlow` 설치 이름을 기대해 실패하며, Teams 배포 구조는 `EventFlowTeams`를 사용한다. GitHub Release·자동 업데이트는 수행하지 않는다.
- 새 검토 EXE는 `C:\Work\02\_EventFlow-web\desktop\teams-v2\release\EventFlowTeamsV2\EventFlowTeamsV2.exe`와 호환 검토 경로에 같은 SHA-256 `491A1CF3CF4012F87A7EE274EB2353651B0C1DA3877C7F7E04C8D7DBE2A78687`로 복사했다. 두 기존 검토 폴더는 `*.backup-20260828-182642`로 보관했고, 지정 경로의 새 EXE는 격리 LOCALAPPDATA에서 10초 기동 및 `--update-health-file`의 `ok`를 확인했다.
- 첫 보정은 Windows Qt 기본 달력 그리기가 `dateTextFormat`의 전경색을 다시 덮어써 실제 화면에서 흐림이 보이지 않았다. `_DirectDateCalendar.paintCell()`이 인접 월 셀을 흰 배경과 `#BAC1CC` 날짜로 마지막에 다시 그리도록 보정했다. 렌더된 팝업에서 해당 색의 픽셀 476개와 전체 마지막 주 표시를 확인했다. 새 검토 EXE SHA-256은 `E1D0D5D5E6A1DA5B7375D95B79A1CFA36DCC6EA56D72132D1E101365A2586A0B`이며, 두 검토 경로에 교체하고 격리 10초 기동과 health `ok`를 재확인했다. 공개 Release·자동 업데이트는 계속 보류한다.
- 체크리스트의 `날짜 비우기`/`닫기`가 마지막 주 위로 겹친 것은 같은 공용 팝업이 버튼 추가 뒤에도 고정 높이 376px을 쓴 결함이었다. 테마 적용 시 실제 layout 높이는 390px이다. `_fit_to_contents()`가 레이아웃의 size hint와 frame 여백으로 높이를 계산하도록 바꿨고, 공용 달력 기본/버튼형 모두 이 기준을 쓴다. 테마 렌더에서 팝업 394px, 달력 하단 339px, 버튼 상단 345px으로 분리됨을 확인했다. 새 검토 EXE SHA-256은 `69BE4F9384BA23E660038DECE7DC771E106CE1E52A97A4B3F08E2E5B9722E85D`이며, 두 검토 경로에 교체하고 격리 10초 기동과 health `ok`를 확인했다. 공개 Release·자동 업데이트는 계속 보류한다.

## 2026-08-28 회사 선택 후 독립 창 순간 표시 보정

- 회사 선택 뒤 Local 업무 화면을 먼저 독립 Windows 창으로 만들었다가 Teams 내부 스택으로 옮기던 구조가 작은 창이 순간 표시되는 원인이었다.
- `MainWindow`에 내장 모드를 추가하고, Teams는 이 창을 처음부터 스택의 자식 위젯으로 생성한다. 따라서 전환 중 별도의 최상위 Local 창이 만들어지지 않는다.
- 회사 선택 회귀 검사는 내장 창의 부모·위젯 타입과 최상위 창 목록 부재를 확인한다. Teams 및 Local GUI 관련 검사 105건, Python compileall, 공백 검사를 통과했다. 새 검토 EXE는 두 검토 경로에 같은 SHA-256 `B5E82D657741A3352EFD501ED1EF88375445675E7292A22EA4EF96C422990CA1`로 교체했다. 공개 Release·자동 업데이트는 사용자 승인 전까지 수행하지 않는다.

## 2026-08-28 회사 선택 시 작은 창 재발·연도 선택 보정

- 이전 진단 기록을 재확인한 결과, 작은 창의 실제 원인은 서버 통신이나 Local 메인 창이 아니라 체크리스트·정산 분류 셀을 구성하는 `CategoryCell`과 내부 `QLabel`이 부모 없이 잠깐 생성되는 것이었다. 이 코드가 현재 V2에 다시 남아 있어 회사 선택 후 작업본 표를 처음 채울 때 재발할 수 있었다.
- 분류 셀은 이제 생성 시점부터 표 viewport의 자식이며, 이름 라벨과 드래그 핸들도 곧바로 해당 셀의 자식이다. 따라서 별도 최상위 Qt 창으로 그려질 기회가 없다. 회귀 검사는 이 부모 관계를 확인한다.
- 공용 날짜 입력 달력의 연도 선택은 읽기 전용 편집 콤보 때문에 오른쪽 화살표만 반응하던 문제였다. 일반 콤보로 바꿔 연도 숫자 중앙을 눌러도 드롭다운이 열리며, 중앙 클릭 검사로 확인했다.
- Teams 및 Local GUI 관련 검사 105건, Python compileall, 공백 검사를 통과했다. 검토 EXE는 두 검토 경로에 같은 SHA-256 `671017EF3BC16AFDF912FC9467FEE1FC156A05E7FC0F2FFB744F527C72505CF5`로 교체했다. 공개 Release·자동 업데이트는 사용자 승인 전까지 수행하지 않는다.

## 2026-08-28 회사 선택 순간 표시 런타임 진단 검토본

- 위의 부모 관계 보정 뒤에도 사용자가 한 차례의 순간 표시를 확인했으므로, 추가 추정 수정은 중단했다. 실제로 표시되는 위젯의 종류와 생성 순서를 확정하기 위한 진단을 Teams V2에 추가했다.
- 검토 앱은 실행할 때마다 `%LOCALAPPDATA%\\EventFlowTeams\\runtime-window-trace.log`를 새로 만들고, 창 표시·숨김·부모 변경·native window 생성 이벤트를 위젯 클래스, 부모 클래스, 플래그, 크기만으로 기록한다. 화면 문구, 사용자 이름, 회사명, 서버 데이터는 기록하지 않는다. 회사 선택/내장 업무창 생성/권한 수신/스냅샷 렌더 완료 시점도 별도 marker로 남긴다.
- 진단 자체의 개인정보 비기록 검사와 Teams/Local GUI 전체 검사를 포함해 Pytest 106건, Python compileall, 공백 검사를 통과했다. 검토 EXE는 두 검토 경로에 같은 SHA-256 `42466F046355A0F7117E9AF75D982683054ABE5C4DA72452AC807C97D9B00363`로 교체했다. 직전 검토 폴더는 각각 `*.backup-20260828-195458`로 보관했다. 공개 Release·자동 업데이트는 사용자 승인 전까지 수행하지 않는다.

## 2026-08-28 회사 선택 버튼 순간 창 확정·수정

- 사용자 재현 로그에서 원인을 확정했다. `TeamsCompanyChoice` 회사 버튼이 부모 없는 native top-level 상태로 `59x40` 크기로 show된 뒤 hide되었고, 이후에야 회사 선택이 시작됐다. 따라서 업무 화면·서버 동기화·체크리스트 렌더가 아닌, 회사 목록을 받은 뒤 버튼을 `setVisible(True)` 하고 layout에 넣는 생성 순서가 원인이었다.
- `OrganizationPage`의 카드·회사 목록·목록 제어 버튼은 처음부터 카드의 자식으로 만들고, 각 회사 버튼은 처음부터 `company_list`의 자식으로 생성한 뒤 layout에 넣는다. 표시 여부는 부모 설정과 layout 추가 뒤에만 바꾼다. 회사 선택 버튼의 부모 관계와 non-window 상태를 회귀 검사로 고정했다.
- Teams/Local GUI Pytest 106건, Python compileall, 공백 검사를 통과했다. 검토 EXE는 두 검토 경로에 같은 SHA-256 `F45BD649B36F808827F0E1A250CFC12DE3DAF7AF8657E2DF53B101A1CD0BA753`로 교체했고, 직전 진단 검토 폴더는 각각 `*.backup-20260828-195912`로 보관했다. 공개 Release·자동 업데이트는 사용자 확인 전까지 수행하지 않는다.

## 2026-08-28 Qt 순간 창 전수 조사·재발 방지 기준

- Teams V2와 내장 Local UI의 모든 Python UI 소스를 대상으로 위젯 생성·소유권 연결·표시 호출을 정적 검사했다. 회사 선택의 실제 원인 외에는 의도하지 않은 부모 없는 표시 경로가 없었고, 두 게스트 초대 화면의 조건부 정산 체크박스도 생성 시 부모를 명시하도록 보정했다.
- `tests/teams_v2/test_widget_ownership_guard.py`는 UI 소스 전체에서 위젯이 부모 또는 layout 소유권을 얻기 전 `show`, `setVisible(True)`, `open`, `exec`, `raise_`, `activateWindow`를 호출하면 실패한다. Local 주 창, 두 업데이트 진행창, 최후의 시작 오류창만 파일·행·클래스로 엄격하게 allowlist한다. 회사 선택 버튼은 실제 show 이벤트에서 부모가 `company_list`인지 확인하는 GUI 회귀 검사도 추가했다.
- `docs/gui-window-ownership-guideline.md`에 부모 지정, 동적 추가 순서, 팝업·독립 창 예외, 변경 전 검사 순서를 문서화했고 `docs/README.md`에서 연결했다. Teams/Local GUI 검사 108건, Python compileall, 공백 검사를 통과했다. 새 검토 EXE는 두 검토 경로에 같은 SHA-256 `DE34BEA8FFDA58A1A1BCF063429AE10A7B0D848C5808B6EDED43072D4042E95E`로 복사했고, 직전 검토 폴더는 각각 `*.backup-20260828-200551`로 보관했다. 공개 Release·자동 업데이트는 수행하지 않는다.

## 2026-08-30 Workspace location

- Repository moved intact from `C:\Work\EventFlow-Teams` to `C:\Work\02_EventFlow\03_EventFlow_Teams` as part of the EventFlow workspace consolidation. Git history, uncommitted work, and Windows build assets were preserved; use the new repository path for future Teams commands.

## 2026-08-30 v0.3.63 공개 배포 준비

- Teams 검토 실행 파일이 8월 28일 빌드본에 머물러 있어, 현재 Teams 변경을 `0.3.63`으로 올렸다. `build_installer.ps1`은 독립 저장소에서 버전을 읽을 때 `src`를 모듈 경로에 포함하도록 보정했다.
- `release\EventFlowTeams\EventFlowTeams.exe`와 `release\installer\EventFlowTeams-Setup-0.3.63.exe`를 만들었다. 격리된 사용자 데이터 폴더에서 패키지 실행 후 `--update-health-file`이 `ok`를 기록하는 것을 확인했다.
- 검증: Teams Pytest 43건 및 Python compileall 통과. 전체 Pytest는 169건 통과했고, 6건은 별도 Local 제품의 과거 `EventFlow.exe`/릴리스 주소 기대값과 Teams 설치 구조가 달라 실패했다. Teams 공개 워크플로는 Teams 전용 검사만 실행한다.
- 이 기록이 포함된 커밋의 `v0.3.63` 태그를 올리면 GitHub Actions가 설치 파일, 자동 업데이트 ZIP, SHA-256 목록을 공개하고 웹의 Windows 다운로드는 최신 설치 파일로 자동 연결된다.
