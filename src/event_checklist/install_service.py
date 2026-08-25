from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import install_dir, update_dir


EXECUTABLE_NAME = "EventFlowTeams.exe"
INSTALL_MARKER_NAME = ".eventflow-teams-installed"
REVIEW_BUILD_FOLDER_NAME = "EventFlowTeams_Current"


def current_executable() -> Path:
    return Path(sys.executable).resolve()


def is_packaged_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_fixed_installation(executable: Path | None = None) -> bool:
    executable = (executable or current_executable()).resolve()
    if executable.name.casefold() != EXECUTABLE_NAME.casefold():
        return False
    return (
        executable.parent == install_dir().resolve()
        or (executable.parent / INSTALL_MARKER_NAME).is_file()
    )


def is_review_build(executable: Path | None = None) -> bool:
    """Return true for the local review build without registering an installation."""
    executable = (executable or current_executable()).resolve()
    return executable.name.casefold() == EXECUTABLE_NAME.casefold() and executable.parent.name == REVIEW_BUILD_FOLDER_NAME


def _ps(value: Path | str) -> str:
    return str(value).replace("'", "''")


def _shortcut_commands(executable: Path) -> str:
    return f"""
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')
foreach ($linkPath in @((Join-Path $desktop '이벤트 플로우.lnk'), (Join-Path $programs '이벤트 플로우.lnk'))) {{
    $shortcut = $shell.CreateShortcut($linkPath)
    $shortcut.TargetPath = '{_ps(executable)}'
    $shortcut.WorkingDirectory = '{_ps(executable.parent)}'
    $shortcut.IconLocation = '{_ps(executable)},0'
    $shortcut.Description = '이벤트 플로우(이플)'
    $shortcut.Save()
}}
"""


def launch_fixed_installation(process_id: int) -> None:
    """Copy the packaged app to its stable per-user folder and restart it there."""
    if not is_packaged_app():
        raise RuntimeError("고정 설치는 패키징된 EventFlowTeams.exe에서만 실행할 수 있습니다.")
    source_executable = current_executable()
    source_dir = source_executable.parent
    if source_executable.name.casefold() != EXECUTABLE_NAME.casefold():
        raise RuntimeError("EventFlowTeams.exe가 포함된 정상 배포 폴더에서 실행해 주세요.")
    if is_fixed_installation(source_executable):
        repair_shortcuts()
        return

    target = install_dir().resolve()
    staging = target.with_name(f"{target.name}.installing")
    old = target.with_name(f"{target.name}.install-old")
    scripts = update_dir()
    scripts.mkdir(parents=True, exist_ok=True)
    script_path = scripts / "install-eventflow-teams.ps1"
    target_executable = target / EXECUTABLE_NAME
    marker = target / INSTALL_MARKER_NAME
    script = f"""$ErrorActionPreference = 'Stop'
$source = '{_ps(source_dir)}'
$target = '{_ps(target)}'
$staging = '{_ps(staging)}'
$old = '{_ps(old)}'
for ($i = 0; $i -lt 120; $i++) {{
    if (-not (Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue)) {{ break }}
    Start-Sleep -Milliseconds 250
}}
if (Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue) {{ throw '이벤트 플로우를 종료하지 못했습니다.' }}
if (Test-Path -LiteralPath $staging) {{ Remove-Item -LiteralPath $staging -Recurse -Force }}
New-Item -ItemType Directory -Path $staging -Force | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination $staging -Recurse -Force
if (-not (Test-Path -LiteralPath (Join-Path $staging '{EXECUTABLE_NAME}'))) {{ throw '설치 파일에 EventFlowTeams.exe가 없습니다.' }}
if (Test-Path -LiteralPath $old) {{ Remove-Item -LiteralPath $old -Recurse -Force }}
$swapped = $false
try {{
    if (Test-Path -LiteralPath $target) {{
        Move-Item -LiteralPath $target -Destination $old
        $swapped = $true
    }}
    Move-Item -LiteralPath $staging -Destination $target
    Set-Content -LiteralPath '{_ps(marker)}' -Encoding ASCII -Value 'EventFlow Teams installed application'
{_shortcut_commands(target_executable)}
    Start-Process -FilePath '{_ps(target_executable)}' -WindowStyle Normal
    if (Test-Path -LiteralPath $old) {{ Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue }}
}} catch {{
    if (Test-Path -LiteralPath $target) {{ Remove-Item -LiteralPath $target -Recurse -Force }}
    if ($swapped -and (Test-Path -LiteralPath $old)) {{ Move-Item -LiteralPath $old -Destination $target }}
    throw
}}
"""
    script_path.write_text(script, encoding="utf-8-sig")
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script_path)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )


def repair_shortcuts() -> None:
    """Ensure the desktop and Start menu shortcuts point to the fixed install."""
    if os.name != "nt" or not is_fixed_installation():
        return
    executable = current_executable()
    scripts = update_dir()
    scripts.mkdir(parents=True, exist_ok=True)
    script_path = scripts / "repair-eventflow-shortcuts.ps1"
    script_path.write_text(
        "$ErrorActionPreference = 'Stop'\n" + _shortcut_commands(executable),
        encoding="utf-8-sig",
    )
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script_path)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )
