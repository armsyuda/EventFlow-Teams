from __future__ import annotations

import sys
import time
from pathlib import Path

from event_checklist import update_service


def main() -> int:
    install_executable = Path(sys.argv[1]).resolve()
    archive = Path(sys.argv[2]).resolve()
    target_version = sys.argv[3]

    update_service.is_packaged_app = lambda: True
    update_service.current_executable = lambda: install_executable
    update_service.is_fixed_installation = lambda _executable=None: True
    info = update_service.UpdateInfo(
        target_version,
        f"v{target_version}",
        "https://example.invalid/EventFlow-Windows.zip",
        "EventFlow-Windows.zip",
        None,
        "",
        "",
    )
    update_service.launch_installer(archive, info, 2_000_000_000)
    log_file = archive.parent / f"update-{target_version}.log"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if log_file.exists():
            text = log_file.read_text(encoding="utf-8-sig")
            if "SUCCESS update completed" in text:
                print(text, end="")
                return 0
            if "FAILED " in text:
                print(text, end="")
                return 1
        time.sleep(0.25)
    print("업데이트 통합 검증 시간이 초과되었습니다.")
    if log_file.exists():
        print(log_file.read_text(encoding="utf-8-sig"), end="")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
