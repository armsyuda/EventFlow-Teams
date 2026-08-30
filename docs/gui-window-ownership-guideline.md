# Qt 위젯 소유권·순간 창 방지 가이드

## 목적

EventFlow Teams는 하나의 주 창 안에서 로그인, 회사 선택, Local 업무 화면을 전환한다. Qt 위젯을 부모 없이 만든 뒤 이미 보이는 화면에서 `show()` 또는 `setVisible(True)` 하면, Qt가 그 위젯을 짧게 독립 native 창으로 표시할 수 있다. 이 문서는 그 순간 창·깜빡임·포커스 이동을 막는 필수 기준이다.

적용 범위는 `src/eventflow_teams_v2`와 Teams가 내장해 쓰는 `src/event_checklist`의 모든 PySide6 UI다.

## 필수 규칙

1. 화면 안에 들어갈 위젯은 생성할 때 부모를 준다.

   ```python
   save_button = QPushButton("저장", panel)
   title = QLabel("제목", panel)
   calendar = QWidget(panel)
   ```

2. 런타임에 추가하는 위젯은 부모를 지정하고 layout에 넣은 다음에만 표시 상태를 바꾼다.

   ```python
   company_button = QPushButton(company.name, self.company_list)
   self.company_layout.addWidget(company_button)
   company_button.setVisible(is_initially_visible)
   ```

   다음 순서는 금지다. 이미 보이는 페이지에서 작은 독립 창이 한 프레임 나타날 수 있다.

   ```python
   company_button = QPushButton(company.name)
   company_button.setVisible(True)
   self.company_layout.addWidget(company_button)
   ```

3. 대화상자·팝업·메뉴도 호출한 화면을 부모로 지정한다.

   ```python
   dialog = QDialog(self)
   popup = DirectCalendarPopup(self)
   ```

   `move()`, `show()`, `raise_()`, `activateWindow()`, `open()`, `exec()`를 호출하기 전에 부모가 확정되어 있어야 한다.

4. 독립 창은 예외다. 업데이트 진행창과 앱 시작 불능 시의 오류창처럼 독립 창이어야 하는 경우만 허용한다. 새 예외를 만들면 다음을 함께 제출한다.

   - 독립 창이어야 하는 사용자 이유
   - 호출 파일·행·클래스
   - `tests/teams_v2/test_widget_ownership_guard.py`의 allowlist 등록
   - 해당 창이 정상 종료·주 창 복귀에 영향을 주지 않는 자동 검사

5. `setParent()`로 나중에 옮기는 방식은 기존 위젯의 구조 변경에만 제한한다. 새 화면 위젯을 만들 때는 이 방식을 사용하지 않는다. 특히 `show()` 뒤 `setParent()`는 금지다.

6. 레이아웃에 곧바로 넣는 정적 라벨·버튼도 가능하면 부모를 생성자에 명시한다. 부모 없는 단순 정적 위젯은 페이지가 아직 보이지 않는 초기 구성 단계에서만 허용되며, 명시적인 표시 호출을 해서는 안 된다.

## 자동 방어선

`tests/teams_v2/test_widget_ownership_guard.py`는 두 UI 소스 트리 전체를 정적으로 검사한다. PySide6 위젯이 부모 또는 layout 소유권을 얻기 전에 다음 호출을 하면 검사가 실패한다.

- `show`, `setVisible(True)`, `open`, `exec`, `raise_`, `activateWindow`

독립 창 예외는 동일 테스트 파일의 `TOP_LEVEL_WINDOW_ALLOWLIST`에 파일·행·클래스로 한정한다. 와일드카드 예외는 허용하지 않는다.

`tests/teams_v2/test_app_shell.py`의 회사 선택 회귀 검사는 실제로 보이는 회사 선택 화면에서 회사 버튼이 표시되는 순간의 부모를 기록한다. 이 검사는 회사 버튼이 native top-level이 되는 회귀를 직접 잡는다.

문제 재현이 필요한 경우에는 Teams V2의 `RuntimeWindowTrace`를 사용한다. `%LOCALAPPDATA%\\EventFlowTeams\\runtime-window-trace.log`에는 위젯 클래스, 부모 클래스, 표시·숨김·부모 변경, 플래그, 크기만 기록한다. 화면 문구, 회사명, 사용자 정보, 서버 데이터는 기록하지 않는다.

## 변경 전 확인 순서

1. 새로 만들 위젯이 주 창 내부인지, 의도된 독립 창인지 먼저 결정한다.
2. 내부 위젯이면 생성자에 부모를 전달한다.
3. 동적으로 추가하면 `addWidget`/`setWidget`/`setCellWidget` 등으로 소유권을 먼저 연결한다.
4. 그 다음에만 보이기·숨기기·이동·활성화를 수행한다.
5. 최소 다음 검사를 실행한다.

   ```powershell
   python -m pytest tests\teams_v2\test_widget_ownership_guard.py tests\teams_v2\test_app_shell.py -q
   ```

6. 회사 선택, 새 카드 추가, 표 셀 추가, 달력 팝업처럼 화면이 이미 보이는 상태에서 위젯을 만드는 기능은 실제 화면에서 한 번 확인한다.

## 2026-08-28 전수 조사 결과

- 대상: 두 UI 소스 트리의 모든 Python 파일과 위젯 생성·표시 경로.
- 확인된 실제 결함: 회사 목록 응답 뒤 `TeamsCompanyChoice` 버튼을 부모 없이 만들고 표시한 뒤 layout에 넣고 있었다. 재현 로그에서는 `59x40` native top-level 창으로 표시됐다가 숨겨졌다.
- 함께 보정한 경로: 회사 선택 카드의 메시지·목록·제어 버튼과 두 게스트 초대 화면의 조건부 정산 체크박스도 생성 시 부모를 명시했다.
- 기존 보정 유지: Local 업무 화면은 Teams 스택의 자식으로 생성하며, 체크리스트·정산 분류 셀과 내부 라벨도 표 viewport/셀의 자식으로 생성한다.
- 결과: 현재 소스는 자동 소유권 검사에서 허용된 독립 창 네 곳(Local 주 창, 두 업데이트 진행창, 최후의 시작 오류창) 외에 부모 없는 상태로 표시되는 위젯이 없다.
