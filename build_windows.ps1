$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$outputName = 'EventFlowTeams'
$releaseRoot = Join-Path $root 'release'
$releaseFolder = Join-Path $releaseRoot $outputName
$releaseExe = Join-Path $releaseFolder "$outputName.exe"

if (-not (Test-Path -LiteralPath $python)) { throw 'Teams V2 Python 환경을 찾을 수 없습니다.' }
if (Test-Path -LiteralPath $releaseExe) {
  $locked = Get-Process -Name $outputName -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $releaseExe }
  if ($locked) { throw "현재 검토 실행 파일이 열려 있습니다. 종료한 뒤 다시 빌드해 주세요.`n$releaseExe" }
}

Push-Location $root
try {
  & $python -m PyInstaller --noconfirm --clean --windowed --name $outputName --icon 'src\event_checklist\resources\assets\event_flow_teams.ico' --distpath $releaseRoot --workpath build `
    --collect-all reportlab --collect-all keyring --collect-all websocket `
    --runtime-hook runtime_hook_pyside6.py `
    --add-data 'src\event_checklist\resources;event_checklist\resources' --paths src eventflow_teams_v2_entry.py
  if ($LASTEXITCODE -ne 0) { throw 'Teams V2 실행 파일 빌드에 실패했습니다.' }

  # Qt6Core on Windows uses the OS ICU bridge. The desktop build environment
  # can expose Poppler's incompatible ICU DLLs on PATH, which prevents QtCore
  # from loading before the app starts. Bundle the matching Windows ICU bridge.
  $runtimeFolder = Join-Path $releaseFolder '_internal'
  foreach ($icuName in @('icu.dll', 'icuin.dll', 'icuuc.dll')) {
    $icuSource = Join-Path $env:WINDIR "System32\$icuName"
    if (-not (Test-Path -LiteralPath $icuSource)) { throw "Windows ICU 런타임을 찾을 수 없습니다: $icuSource" }
    $icuDestination = Join-Path $runtimeFolder $icuName
    Copy-Item -LiteralPath $icuSource -Destination $icuDestination -Force
    # System32 ICU files carry a read-only attribute. Clear it on the private
    # copy so the next PyInstaller --clean build can replace it safely.
    (Get-Item -LiteralPath $icuDestination).Attributes = 'Archive'
  }

  # Desktop clients use only the same publishable connection values as Web.
  $webEnv = Join-Path $root '.env.local'
  if (-not (Test-Path -LiteralPath $webEnv)) { $webEnv = Join-Path $root '.env' }
  if (-not (Test-Path -LiteralPath $webEnv)) { throw '공개 Supabase 연결값 파일을 찾을 수 없습니다. GitHub Actions에서는 Repository Variables를 사용하세요.' }
  $values = @{}
  Get-Content $webEnv | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.*)$') { $values[$matches[1].Trim()] = $matches[2].Trim().Trim('"').Trim("'") }
  }
  if (-not $values['PUBLIC_SUPABASE_URL'] -or -not $values['PUBLIC_SUPABASE_PUBLISHABLE_KEY']) { throw 'Supabase 공개 연결값이 비어 있습니다.' }
  @(
    "EVENTFLOW_SUPABASE_URL=$($values['PUBLIC_SUPABASE_URL'])",
    "EVENTFLOW_SUPABASE_PUBLISHABLE_KEY=$($values['PUBLIC_SUPABASE_PUBLISHABLE_KEY'])"
  ) | Set-Content -Encoding utf8 (Join-Path $releaseFolder "$outputName.env")
  Write-Output "BUILT $releaseExe"
}
finally { Pop-Location }
