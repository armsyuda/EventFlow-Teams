from __future__ import annotations

import hashlib
import json
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config import update_dir
from .install_service import (
    INSTALL_MARKER_NAME,
    current_executable,
    is_fixed_installation,
    is_packaged_app,
)

REPOSITORY = "armsyuda/EventFlow-Teams"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
PREFERRED_ASSET = "EventFlowTeams-Windows.zip"


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    asset_url: str
    asset_name: str
    asset_digest: str | None
    release_url: str
    notes: str
    published_at: str = ""


class UpdateCheckError(RuntimeError):
    pass


class UpdateDownloadError(RuntimeError):
    pass


def _http_failure_message(exc: urllib.error.HTTPError, action: str) -> str:
    if exc.code == 404:
        reason = "GitHub에서 공개된 최신 릴리스 또는 업데이트 파일을 찾지 못했습니다."
        guide = "저장소와 Release가 공개 상태인지, 최신 Release가 초안이 아닌지, Windows ZIP 파일이 첨부되어 있는지 확인하세요."
    elif exc.code in (401, 403):
        reason = "GitHub가 요청을 허용하지 않았습니다. 요청 한도 초과, 사내 보안망 차단 또는 비공개 저장소일 수 있습니다."
        guide = "잠시 후 다시 시도하고, 브라우저에서 GitHub가 열리는지와 방화벽·보안 프로그램의 차단 여부를 확인하세요."
    elif exc.code == 429:
        reason = "짧은 시간에 요청이 많아 GitHub가 일시적으로 확인을 제한했습니다."
        guide = "몇 분 뒤 다시 확인하세요."
    elif 500 <= exc.code:
        reason = "GitHub 서버가 일시적으로 정상 응답하지 않았습니다."
        guide = "잠시 후 다시 시도하세요."
    else:
        reason = f"GitHub 서버가 요청을 처리하지 못했습니다."
        guide = "인터넷 연결과 GitHub 접속 상태를 확인한 뒤 다시 시도하세요."
    return f"{action}하지 못했습니다.\n\n확인된 원인\n{reason}\n\n확인 방법\n{guide}\n\n오류 상세: HTTP {exc.code} {exc.reason or ''}".rstrip()


def _network_failure_message(exc: BaseException, action: str) -> str:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        cause = "GitHub 응답 시간이 초과되었습니다. 인터넷이 느리거나 GitHub 연결이 차단되었을 수 있습니다."
        guide = "인터넷 연결을 확인하고 잠시 후 다시 시도하세요."
    elif isinstance(reason, ssl.SSLError):
        cause = "보안 연결 인증서(SSL)를 확인하지 못했습니다. PC 날짜·시간 오류나 보안 프로그램의 HTTPS 검사가 원인일 수 있습니다."
        guide = "Windows 날짜와 시간을 맞춘 뒤, 보안 프로그램이나 사내망의 HTTPS 차단 여부를 확인하세요."
    elif isinstance(reason, socket.gaierror):
        cause = "GitHub 주소를 찾지 못했습니다. 인터넷 또는 DNS 연결 문제입니다."
        guide = "브라우저에서 github.com이 열리는지 확인하고 네트워크를 다시 연결하세요."
    elif isinstance(reason, ConnectionRefusedError):
        cause = "GitHub 연결이 거부되었습니다. 방화벽, 보안 프로그램 또는 사내망이 연결을 막았을 수 있습니다."
        guide = "브라우저에서 GitHub 접속 여부와 보안 프로그램의 차단 기록을 확인하세요."
    else:
        cause = "GitHub에 연결하지 못했습니다. 인터넷 연결, 방화벽 또는 보안 프로그램의 차단 가능성이 있습니다."
        guide = "브라우저에서 GitHub가 열리는지 확인한 뒤 다시 시도하세요."
    return f"{action}하지 못했습니다.\n\n확인된 원인\n{cause}\n\n확인 방법\n{guide}\n\n오류 상세: {type(reason).__name__}: {reason}"


def version_tuple(value: str) -> tuple[int, ...]:
    clean = value.strip().lstrip("vV").split("-", 1)[0]
    try:
        return tuple(int(part) for part in clean.split("."))
    except ValueError:
        return (0,)


def fetch_latest_release(timeout: float = 6.0) -> UpdateInfo:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"EventFlowTeams/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            release = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpdateCheckError(_http_failure_message(exc, "업데이트를 확인")) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise UpdateCheckError(_network_failure_message(exc, "업데이트를 확인")) from exc
    except json.JSONDecodeError as exc:
        raise UpdateCheckError(
            "업데이트를 확인하지 못했습니다.\n\n확인된 원인\nGitHub 응답을 읽을 수 없는 형식으로 받았습니다. "
            "보안 프로그램이나 사내망이 응답 내용을 바꿨을 수 있습니다.\n\n확인 방법\n브라우저에서 업데이트 확인 주소가 "
            f"정상적인 글자로 표시되는지 확인하세요.\n\n오류 상세: JSON {exc.msg}"
        ) from exc
    tag = str(release.get("tag_name") or "")
    if not tag:
        raise UpdateCheckError(
            "업데이트를 확인하지 못했습니다.\n\n확인된 원인\n공개 Release에 버전 태그가 없습니다.\n\n"
            "확인 방법\nGitHub Release를 v0.3.25 같은 버전 태그로 다시 공개하세요."
        )
    assets = list(release.get("assets") or [])
    asset = next((entry for entry in assets if entry.get("name") == PREFERRED_ASSET), None)
    if asset is None:
        asset = next((entry for entry in assets if str(entry.get("name", "")).lower().endswith(".zip")
                      and "eventflow" in str(entry.get("name", "")).lower()), None)
    if asset is None:
        return UpdateInfo(tag.lstrip("vV"), tag, "", "", None,
                          str(release.get("html_url") or RELEASES_URL), str(release.get("body") or ""),
                          str(release.get("published_at") or ""))
    url = str(asset.get("browser_download_url") or "")
    expected_prefix = f"https://github.com/{REPOSITORY}/releases/download/"
    if not url.startswith(expected_prefix):
        raise UpdateCheckError(
            "업데이트를 확인했지만 자동 설치 파일 주소가 예상한 GitHub 저장소와 다릅니다.\n\n"
            "확인 방법\nRelease에 이 프로젝트에서 직접 만든 EventFlowTeams-Windows.zip을 다시 첨부하세요.\n\n"
            f"오류 상세: {url or '다운로드 주소 없음'}"
        )
    return UpdateInfo(
        tag.lstrip("vV"), tag, url, str(asset.get("name") or PREFERRED_ASSET),
        str(asset.get("digest")) if asset.get("digest") else None,
        str(release.get("html_url") or RELEASES_URL), str(release.get("body") or ""),
        str(release.get("published_at") or ""),
    )


def check_for_update(timeout: float = 6.0) -> UpdateInfo | None:
    """호환용 API: 공개 릴리스가 현재 앱보다 새 버전일 때만 반환한다."""
    info = fetch_latest_release(timeout)
    return info if version_tuple(info.version) > version_tuple(__version__) else None


def download_update(info: UpdateInfo, timeout: float = 90.0) -> Path:
    if not info.asset_url:
        raise UpdateDownloadError(
            "업데이트를 설치할 수 없습니다.\n\n확인된 원인\n공개 Release에 자동 설치용 EventFlowTeams-Windows.zip이 없습니다.\n\n"
            "확인 방법\nGitHub Release에 Windows ZIP 파일을 첨부한 뒤 다시 시도하세요."
        )
    downloads = update_dir()
    downloads.mkdir(parents=True, exist_ok=True)
    destination = downloads / f"EventFlowTeams-{info.version}.zip"
    request = urllib.request.Request(info.asset_url, headers={"User-Agent": f"EventFlowTeams/{__version__}"})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk); digest.update(chunk)
    except urllib.error.HTTPError as exc:
        destination.unlink(missing_ok=True)
        raise UpdateDownloadError(_http_failure_message(exc, "업데이트 파일을 다운로드")) from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        destination.unlink(missing_ok=True)
        raise UpdateDownloadError(_network_failure_message(exc, "업데이트 파일을 다운로드")) from exc
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise UpdateDownloadError(
            "업데이트 파일을 저장하지 못했습니다.\n\n확인된 원인\n업데이트 폴더에 파일을 쓸 수 없거나 디스크 공간이 부족합니다.\n\n"
            f"확인 방법\n디스크 여유 공간과 Windows 보안의 폴더 차단 기록을 확인하세요.\n\n오류 상세: {type(exc).__name__}: {exc}"
        ) from exc
    if info.asset_digest and info.asset_digest.lower().startswith("sha256:"):
        expected = info.asset_digest.split(":", 1)[1].lower()
        if digest.hexdigest().lower() != expected:
            destination.unlink(missing_ok=True)
            raise UpdateDownloadError(
                "업데이트 파일을 설치하지 않았습니다.\n\n확인된 원인\n다운로드한 파일의 보안 검증값이 GitHub의 값과 다릅니다. "
                "파일이 손상되었거나 중간에서 변경되었을 수 있습니다.\n\n확인 방법\n잠시 후 다시 내려받으세요. 계속 반복되면 Release 파일을 다시 올려야 합니다."
            )
    return destination


def launch_installer(archive: Path, info: UpdateInfo, process_id: int) -> None:
    if not is_packaged_app():
        raise RuntimeError("자동 설치는 패키징된 EventFlowTeams.exe에서만 실행할 수 있습니다.")
    executable = current_executable()
    install_dir = executable.parent
    if not is_fixed_installation(executable):
        raise RuntimeError("고정 설치된 이벤트 플로우에서만 앱 내부 업데이트를 적용할 수 있습니다.")
    script_dir = archive.parent
    script_path = script_dir / f"apply-{info.version}.ps1"

    def ps(value: Path | str) -> str:
        return str(value).replace("'", "''")

    staging = script_dir / f"staging-{info.version}"
    old_dir = install_dir.with_name(f"{install_dir.name}.update-old")
    health_file = script_dir / f"health-{info.version}.ok"
    log_file = script_dir / f"update-{info.version}.log"
    state_file = script_dir / f"update-{info.version}.state"
    indicator_path = script_dir / f"indicator-{info.version}.ps1"
    marker_path = install_dir / INSTALL_MARKER_NAME

    indicator = f"""Add-Type -AssemblyName PresentationFramework
$statePath = '{ps(state_file)}'
[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="이플 업데이트" Width="420" Height="214" WindowStyle="None"
        ResizeMode="NoResize" WindowStartupLocation="CenterScreen" Topmost="True"
        Background="Transparent" AllowsTransparency="True" ShowInTaskbar="True">
  <Border Background="#FFFFFF" BorderBrush="#E5E7EB" BorderThickness="1" CornerRadius="18" Padding="28,24">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/><RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/><RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>
      <StackPanel Grid.Row="0" Orientation="Horizontal">
        <Border Width="46" Height="46" Background="#F25B24" CornerRadius="12">
          <TextBlock Text="이플" Foreground="White" FontFamily="Malgun Gothic" FontSize="15" FontWeight="Bold"
                     HorizontalAlignment="Center" VerticalAlignment="Center"/>
        </Border>
        <StackPanel Margin="12,1,0,0">
          <TextBlock Text="이벤트 플로우" Foreground="#212124" FontFamily="Malgun Gothic" FontSize="21" FontWeight="Bold"/>
          <TextBlock Text="새 버전 {info.version}" Foreground="#868B94" FontFamily="Malgun Gothic" FontSize="12"/>
        </StackPanel>
      </StackPanel>
      <TextBlock Name="StatusText" Grid.Row="2" Text="업데이트를 준비하고 있습니다…" Foreground="#686B70"
                 FontFamily="Malgun Gothic" FontSize="13" VerticalAlignment="Center"/>
      <ProgressBar Grid.Row="3" Height="7" IsIndeterminate="True" Foreground="#F25B24" Background="#FFF0E8" BorderThickness="0"/>
    </Grid>
  </Border>
</Window>
'@
$reader = New-Object System.Xml.XmlNodeReader $xaml
$window = [Windows.Markup.XamlReader]::Load($reader)
$status = $window.FindName('StatusText')
$script:terminalTicks = 0
$timer = New-Object Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(250)
$timer.Add_Tick({{
    try {{ $value = (Get-Content -LiteralPath $statePath -Raw -ErrorAction Stop).Trim() }} catch {{ $value = 'PREPARING' }}
    if ($value -eq 'WAITING') {{ $status.Text = '실행 중인 이플을 안전하게 종료하고 있습니다…' }}
    elseif ($value -eq 'INSTALLING') {{ $status.Text = '새 버전을 설치하고 있습니다…' }}
    elseif ($value -eq 'RESTARTING') {{ $status.Text = '설치를 마치고 이플을 다시 시작하고 있습니다…' }}
    elseif ($value -eq 'SUCCESS') {{ $status.Text = '업데이트가 완료되었습니다.'; $script:terminalTicks++ }}
    elseif ($value.StartsWith('FAILED')) {{ $status.Text = '업데이트하지 못해 이전 버전으로 복구했습니다.'; $script:terminalTicks++ }}
    else {{ $status.Text = '업데이트를 준비하고 있습니다…' }}
    if ($script:terminalTicks -ge 6) {{ $timer.Stop(); $window.Close() }}
}})
$timer.Start()
$null = $window.ShowDialog()
"""
    indicator_path.write_text(indicator, encoding="utf-8-sig")
    state_file.write_text("PREPARING", encoding="ascii")
    script = f"""$ErrorActionPreference = 'Stop'
$archive = '{ps(archive)}'
$staging = '{ps(staging)}'
$install = '{ps(install_dir)}'
$old = '{ps(old_dir)}'
$exe = Join-Path $install 'EventFlowTeams.exe'
$health = '{ps(health_file)}'
$log = '{ps(log_file)}'
$state = '{ps(state_file)}'
$scriptRoot = '{ps(script_dir)}'
function Set-UpdateState([string]$value) {{
    try {{ Set-Content -LiteralPath $state -Encoding ASCII -Value $value }} catch {{}}
}}
function Write-UpdateLog([string]$message) {{
    # A log reader (support tool, antivirus, or Explorer preview) can briefly
    # lock the file. Diagnostics must never be able to cancel an update.
    try {{
        Add-Content -LiteralPath $log -Encoding UTF8 -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff') $message"
    }} catch {{
        # Best-effort logging only; the install/rollback path remains primary.
    }}
}}
$swapped = $false
try {{
    Set-Location -LiteralPath $scriptRoot
    if (Test-Path -LiteralPath $log) {{ Remove-Item -LiteralPath $log -Force }}
    Set-UpdateState 'WAITING'
    Write-UpdateLog 'START waiting for the previous app process'
    for ($i = 0; $i -lt 120; $i++) {{
        if (-not (Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue)) {{ break }}
        Start-Sleep -Milliseconds 500
    }}
    if (Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue) {{ throw '이벤트 플로우를 종료하지 못했습니다.' }}
    Set-UpdateState 'INSTALLING'
    Write-UpdateLog 'EXTRACT update archive'
    if (Test-Path -LiteralPath $staging) {{ Remove-Item -LiteralPath $staging -Recurse -Force }}
    New-Item -ItemType Directory -Path $staging | Out-Null
    Expand-Archive -LiteralPath $archive -DestinationPath $staging -Force
    $payload = $staging
    $nested = Join-Path $staging 'EventFlowTeams'
    if (Test-Path -LiteralPath (Join-Path $nested 'EventFlowTeams.exe')) {{ $payload = $nested }}
    if (-not (Test-Path -LiteralPath (Join-Path $payload 'EventFlowTeams.exe'))) {{ throw '업데이트 파일에 EventFlowTeams.exe가 없습니다.' }}
    if (Test-Path -LiteralPath $old) {{ Remove-Item -LiteralPath $old -Recurse -Force }}
    if (Test-Path -LiteralPath $health) {{ Remove-Item -LiteralPath $health -Force }}
    Write-UpdateLog 'SWAP installed application folder'
    Move-Item -LiteralPath $install -Destination $old
    $swapped = $true
    Move-Item -LiteralPath $payload -Destination $install
    Set-Content -LiteralPath '{ps(marker_path)}' -Encoding ASCII -Value 'EventFlow Teams installed application'
    if (Test-Path -LiteralPath $old) {{
        Get-ChildItem -LiteralPath $old -Filter 'unins*' -File -ErrorAction SilentlyContinue |
            Copy-Item -Destination $install -Force -ErrorAction SilentlyContinue
    }}
    Set-UpdateState 'RESTARTING'
    Write-UpdateLog 'LAUNCH updated application'
    $newProcess = Start-Process -FilePath $exe -ArgumentList @('--update-health-file', $health, '--restarting-after-update') -WindowStyle Normal -PassThru
    for ($i = 0; $i -lt 120; $i++) {{
        if (Test-Path -LiteralPath $health) {{ break }}
        if ($newProcess.HasExited) {{ break }}
        Start-Sleep -Milliseconds 250
    }}
    if (-not (Test-Path -LiteralPath $health)) {{
        if (-not $newProcess.HasExited) {{ Stop-Process -Id $newProcess.Id -Force }}
        throw '새 버전이 정상적으로 시작되지 않아 이전 버전으로 되돌립니다.'
    }}
    Remove-Item -LiteralPath $health -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $staging) {{ Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue }}
    Write-UpdateLog 'SUCCESS update completed'
    Set-UpdateState 'SUCCESS'
}} catch {{
    $failure = $_.Exception.Message
    Write-UpdateLog "FAILED $failure"
    Set-UpdateState "FAILED $failure"
    if ($swapped) {{
        if (Test-Path -LiteralPath $install) {{ Remove-Item -LiteralPath $install -Recurse -Force }}
        if (Test-Path -LiteralPath $old) {{ Move-Item -LiteralPath $old -Destination $install }}
    }}
    if (Test-Path -LiteralPath $exe) {{
        Write-UpdateLog 'RECOVERY relaunch previous application'
        Start-Process -FilePath $exe -WindowStyle Normal
    }}
    exit 1
}}
"""
    script_path.write_text(script, encoding="utf-8-sig")
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(indicator_path)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
        cwd=str(script_dir),
    )
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script_path)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
        cwd=str(script_dir),
    )
