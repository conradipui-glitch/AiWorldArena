param(
    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 8000,
    [ValidateRange(1024, 65535)]
    [int]$UiPort = 5173
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = 'python'
}

foreach ($port in @($ApiPort, $UiPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the existing local service or choose another port."
    }
}

$Work = Join-Path $Root 'work'
New-Item -ItemType Directory -Force -Path $Work | Out-Null

Start-Process -FilePath $Python `
    -ArgumentList "-m uvicorn ai_society.api.app:app --host 127.0.0.1 --port $ApiPort" `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Work 'observer-api.log') `
    -RedirectStandardError (Join-Path $Work 'observer-api.err.log') | Out-Null

Start-Process -FilePath 'cmd.exe' `
    -ArgumentList "/c npm run dev -- --host 127.0.0.1 --port $UiPort" `
    -WorkingDirectory (Join-Path $Root 'client') `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Work 'observer-ui.log') `
    -RedirectStandardError (Join-Path $Work 'observer-ui.err.log') | Out-Null

Write-Output "Observer is starting at http://127.0.0.1:$UiPort"
