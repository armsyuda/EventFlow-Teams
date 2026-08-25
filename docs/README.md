# Teams V2 데스크톱 구조

`src/event_checklist`은 Local 0.3.48 기준본이다. Teams 기능을 이 폴더에 넣지 않는다.

`src/eventflow_teams_v2`만 다음 역할을 맡는다.

- `app.py`: 로그인, 회사 선택·전환·로그아웃, Local 창 연결, 제목줄 상태등
- `api.py`: Supabase 인증·현재 사용자 활성 회사·권한 RPC 호출
- `session.py`: Windows 자격 증명 관리자 `EventFlowTeamsV2` 토큰 저장
- `workspace.py`: 사용자·회사별 V2 SQLite 경로·메타데이터·로그아웃 정리
- `permissions.py`: 서버 권한 코드를 Local UI의 읽기/편집 가능 상태로 적용

동기화, Realtime, 충돌 처리, 서버 snapshot RPC는 단계 3~4에서 같은 V2 패키지에 추가한다. Local 기준본을 수정하지 않는 원칙을 유지한다.
