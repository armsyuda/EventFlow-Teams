# EventFlow Teams 작업 연속성

## 2026-08-25 독립 GitHub 배포 및 Windows 설치

- 최신 Teams V2 실행본을 이 독립 저장소로 옮기고, `armsyuda/EventFlow-Teams` GitHub Release를 자동 업데이트 원본으로 지정했다. 업데이트 파일은 `EventFlowTeams-Windows.zip`, 실행 파일은 `EventFlowTeams.exe`로 고정한다.
- Inno Setup 설치 프로그램은 관리자 권한 없이 `%LOCALAPPDATA%\Programs\EventFlow Teams`에 설치한다. Windows 앱 목록에서 제거할 수 있으며, 제거는 프로그램 폴더만 지우고 로그인 정보·작업 데이터가 있는 `%LOCALAPPDATA%\EventFlowTeams`는 보존한다.
- 설치 완료 시 `.eventflow-teams-installed` 마커를 만든다. 앱 내 업데이트는 GitHub Release SHA-256 digest를 확인하고, 교체·재기동 실패 시 기존 프로그램 폴더를 복구한다.
- GitHub Actions `Windows release`는 `v*` 태그에서 테스트·PyInstaller·Inno Setup·업데이트 ZIP·SHA256SUMS·GitHub Release를 수행한다. 실행 전 Repository Variables `EVENTFLOW_SUPABASE_URL`, `EVENTFLOW_SUPABASE_PUBLISHABLE_KEY`가 필요하다. 값은 source control에 저장하지 않는다.
- 검증: Pytest 156건, compileall, Inno 설치 파일 생성, 별도 테스트 폴더에서 설치 0/실행 유지/제거 0/프로그램 폴더 삭제를 확인했다. 배포본은 아직 코드 서명되지 않았으므로 공식 배포 전 조직 인증서 서명이 남은 보안 작업이다.
