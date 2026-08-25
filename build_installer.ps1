param([switch]$SkipAppBuild)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$compilerPaths = @(
  (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
  'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
  'C:\Program Files\Inno Setup 6\ISCC.exe'
)
$compiler = $compilerPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not (Test-Path -LiteralPath $python)) { throw '프로젝트 Python 환경을 찾을 수 없습니다.' }
if (-not $compiler) { throw 'Inno Setup 6을 찾을 수 없습니다.' }

Push-Location $root
try {
  if (-not $SkipAppBuild) {
    & (Join-Path $root 'build_windows.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Teams 실행 파일 빌드에 실패했습니다.' }
  }
  $version = & $python -c "from event_checklist import __version__; print(__version__)"
  & $compiler "/DAppVersion=$version" (Join-Path $root 'installer\EventFlowTeams.iss')
  if ($LASTEXITCODE -ne 0) { throw '설치 프로그램 생성에 실패했습니다.' }
  Write-Output "BUILT $(Join-Path $root "release\installer\EventFlowTeams-Setup-$version.exe")"
}
finally { Pop-Location }
