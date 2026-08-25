# EventFlow Teams

회사별 행사 업무를 함께 관리하는 Windows 데스크톱 앱입니다. 로그인, 회사별 권한, 실시간 동기화 및 로컬 작업본을 제공합니다.

## 사용자 설치

GitHub Releases에서 `EventFlowTeams-Setup-x.y.z.exe`를 내려받아 실행합니다. 기본 설치 위치는 `%LOCALAPPDATA%\Programs\EventFlow Teams`이며 관리자 권한이 필요하지 않습니다. Windows 앱 목록의 **EventFlow Teams 제거**로 프로그램을 삭제할 수 있습니다. 로그인 정보와 사용자 작업 데이터는 별도 사용자 폴더에 보관되므로 제거 과정에서 지워지지 않습니다.

## 자동 업데이트

앱은 이 저장소의 최신 GitHub Release를 확인합니다. 새 버전이 있으면 `EventFlowTeams-Windows.zip`을 SHA-256 값과 함께 검증하고, 현재 앱을 종료한 뒤 교체·재시작합니다. 오류가 나면 기존 프로그램 폴더로 되돌립니다.

## 개발 및 검증

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe -m pytest -q
```

로컬 빌드는 client-safe Supabase URL과 publishable key만 포함한 `.env` 또는 `.env.local`이 필요합니다. 예시는 `.env.example`을 참고합니다.

```powershell
.\build_installer.ps1
```

이 명령은 `release\installer\EventFlowTeams-Setup-x.y.z.exe`를 만듭니다. GitHub에서 `v*` 태그를 올리면 Actions가 같은 검증, 설치 파일, 자동 업데이트 ZIP 및 SHA-256 목록을 Release에 게시합니다. Actions 실행 전 Repository Variables `EVENTFLOW_SUPABASE_URL`, `EVENTFLOW_SUPABASE_PUBLISHABLE_KEY`를 설정해야 합니다.

## 배포 주의사항

현재 설치 프로그램은 코드 서명되지 않았습니다. 배포 전 조직 명의의 Windows 코드 서명 인증서로 EXE와 설치 프로그램에 서명하면 SmartScreen 신뢰도와 게시자 식별을 강화할 수 있습니다.
