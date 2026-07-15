param(
    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 18000,
    [ValidateRange(1024, 65535)]
    [int]$UiPort = 15173
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Ports = @($ApiPort, $UiPort)

$occupied = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $Ports -contains $_.LocalPort }
if ($occupied) {
    throw "Порты smoke-проверки уже заняты: $($occupied.LocalPort -join ', ')."
}

$environmentNames = @(
    'AIWORLD_API_PORT',
    'AIWORLD_UI_PORT',
    'AIWORLD_NO_BROWSER',
    'AIWORLD_NO_PAUSE'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    $env:AIWORLD_API_PORT = $ApiPort
    $env:AIWORLD_UI_PORT = $UiPort
    $env:AIWORLD_NO_BROWSER = '1'
    $env:AIWORLD_NO_PAUSE = '1'

    Push-Location $Root
    try {
        & cmd.exe /d /c 'call START_AIWORLD_ARENA.bat'
        if ($LASTEXITCODE -ne 0) {
            throw "START_AIWORLD_ARENA.bat завершился с кодом $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }

    $api = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 5
    $uiHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$UiPort/health" -TimeoutSec 5
    $page = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$UiPort/" -TimeoutSec 5
    if ($api.status -ne 'ok' -or $uiHealth.status -ne 'ok' -or $page.StatusCode -ne 200) {
        throw 'Запущенный наблюдатель не прошёл проверку API, proxy или главной страницы.'
    }
    Write-Output "Smoke запуска пройден: API $ApiPort, UI $UiPort."
} finally {
    $processIds = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $Ports -contains $_.LocalPort } |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($processId in $processIds) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    foreach ($name in $environmentNames) {
        if ($null -eq $previousEnvironment[$name]) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        } else {
            Set-Item "Env:$name" $previousEnvironment[$name]
        }
    }
}
