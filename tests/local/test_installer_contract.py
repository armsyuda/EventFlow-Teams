from pathlib import Path


INSTALLER = Path(__file__).parents[2] / "installer" / "EventFlowTeams.iss"


def test_installer_is_per_user_and_has_an_uninstaller() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert "DefaultDirName={localappdata}\\Programs\\EventFlow Teams" in text
    assert "UninstallDisplayIcon={app}\\{#AppExeName}" in text
    assert 'Type: files; Name: "{app}\\.eventflow-teams-installed"' in text


def test_installer_preserves_user_data_and_supports_safe_updates() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'Source: "..\\release\\EventFlowTeams\\*"; DestDir: "{app}"' in text
    assert "{userappdata}" not in text.lower()
    assert "{commonappdata}" not in text.lower()
    assert "CloseApplications=yes" in text
    assert ".eventflow-teams-installed" in text
