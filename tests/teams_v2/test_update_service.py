from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import pytest

from event_checklist import __version__, install_service, update_service


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_args): self.close()


def test_new_release_is_detected(monkeypatch):
    version_parts = [int(part) for part in __version__.split(".")]
    version_parts[-1] += 1
    newer_version = ".".join(str(part) for part in version_parts)
    payload = {
        "tag_name": f"v{newer_version}",
        "published_at": "2026-08-12T03:00:00Z",
        "html_url": f"https://github.com/armsyuda/EventFlow-Teams/releases/tag/v{newer_version}",
        "body": "새 기능",
        "assets": [{
            "name": "EventFlowTeams-Windows.zip",
            "browser_download_url": f"https://github.com/armsyuda/EventFlow-Teams/releases/download/v{newer_version}/EventFlowTeams-Windows.zip",
            "digest": "sha256:abc",
        }],
    }
    monkeypatch.setattr(update_service.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(json.dumps(payload).encode()))
    info = update_service.check_for_update()
    assert info and info.version == newer_version
    assert info.asset_name == "EventFlowTeams-Windows.zip"
    assert info.published_at == "2026-08-12T03:00:00Z"


def test_latest_release_metadata_is_available_even_without_newer_version(monkeypatch):
    payload = {"tag_name": "v0.3.3", "published_at": "2026-08-11T00:41:19Z", "assets": []}
    monkeypatch.setattr(update_service.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(json.dumps(payload).encode()))
    info = update_service.fetch_latest_release()
    assert info.version == "0.3.3"
    assert info.published_at[:10] == "2026-08-11"


def test_same_release_does_not_enable_update(monkeypatch):
    payload = {"tag_name": "v0.3.3", "assets": []}
    monkeypatch.setattr(update_service.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(json.dumps(payload).encode()))
    assert update_service.check_for_update() is None


def test_download_verifies_github_digest(monkeypatch, tmp_path):
    content = b"event-flow-update"
    digest = hashlib.sha256(content).hexdigest()
    info = update_service.UpdateInfo(
        "0.3.2", "v0.3.2",
        "https://github.com/armsyuda/EventFlow-Teams/releases/download/v0.3.2/EventFlowTeams-Windows.zip",
        "EventFlowTeams-Windows.zip", f"sha256:{digest}", "", "",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(update_service.urllib.request, "urlopen", lambda *_args, **_kwargs: Response(content))
    result = update_service.download_update(info)
    assert result.read_bytes() == content


def test_update_check_reports_network_or_private_repository(monkeypatch):
    monkeypatch.setattr(
        update_service.urllib.request, "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.HTTPError("", 404, "", {}, None)),
    )
    with pytest.raises(update_service.UpdateCheckError, match="HTTP 404") as error:
        update_service.check_for_update()
    assert "공개된 최신 릴리스" in str(error.value)
    assert "확인 방법" in str(error.value)


def test_update_check_reports_dns_failure(monkeypatch):
    failure = urllib.error.URLError(__import__("socket").gaierror(11001, "host not found"))
    monkeypatch.setattr(
        update_service.urllib.request, "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(update_service.UpdateCheckError, match="DNS") as error:
        update_service.fetch_latest_release()
    assert "github.com" in str(error.value)


def test_update_helper_requires_fixed_install_and_health_check(monkeypatch, tmp_path):
    install = tmp_path / "Programs" / "EventFlow Teams"
    executable = install / "EventFlowTeams.exe"
    archive = tmp_path / "updates" / "EventFlowTeams-0.3.4.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"zip")
    launched = {}
    monkeypatch.setattr(update_service, "is_packaged_app", lambda: True)
    monkeypatch.setattr(update_service, "current_executable", lambda: executable)
    monkeypatch.setattr(update_service, "is_fixed_installation", lambda _exe=None: True)
    monkeypatch.setattr(update_service.subprocess, "Popen", lambda args, **kwargs: launched.update(args=args, kwargs=kwargs))
    info = update_service.UpdateInfo("0.3.4", "v0.3.4", "https://example.invalid/update.zip", "EventFlowTeams-Windows.zip", None, "", "")

    update_service.launch_installer(archive, info, 4321)

    script = (archive.parent / "apply-0.3.4.ps1").read_text(encoding="utf-8-sig")
    assert "--update-health-file" in script
    assert "이전 버전으로 되돌립니다" in script
    assert str(install) in script
    assert "Set-Location -LiteralPath $scriptRoot" in script
    assert "update-0.3.4.log" in script
    assert "Diagnostics must never be able to cancel an update" in script
    assert "Add-Content -LiteralPath $log" in script
    assert script.index("try {") < script.index("Expand-Archive")
    assert "RECOVERY relaunch previous application" in script
    assert "--restarting-after-update" in script
    assert ".eventflow-teams-installed" in script
    assert "Set-UpdateState 'INSTALLING'" in script
    assert "Set-UpdateState 'RESTARTING'" in script
    indicator = (archive.parent / "indicator-0.3.4.ps1").read_text(encoding="utf-8-sig")
    assert "이플 업데이트" in indicator
    assert "새 버전 0.3.4" in indicator
    assert "$script:terminalTicks" in indicator
    assert launched["args"][0] == "powershell.exe"
    assert launched["kwargs"]["cwd"] == str(archive.parent)


def test_custom_installer_location_is_recognized(monkeypatch, tmp_path):
    install = tmp_path / "My EventFlow Teams"
    executable = install / "EventFlowTeams.exe"
    install.mkdir()
    executable.write_bytes(b"exe")
    (install / install_service.INSTALL_MARKER_NAME).write_text("installed", encoding="ascii")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert install_service.is_fixed_installation(executable)
