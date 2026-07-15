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
    if (
        $api.status -ne 'ok' -or
        $api.observer_api -ne 'workspace-v1' -or
        $uiHealth.status -ne 'ok' -or
        $uiHealth.observer_api -ne 'workspace-v1' -or
        $page.StatusCode -ne 200
    ) {
        throw 'Запущенный наблюдатель не прошёл проверку API, proxy или главной страницы.'
    }

    $emptyWorlds = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/v1/runs" -TimeoutSec 5
    if ($null -eq $emptyWorlds.runs -or $emptyWorlds.runs.Count -ne 0) {
        throw 'Рабочее пространство не открылось в ожидаемом пустом состоянии.'
    }

    $runRequest = @{
        seed = 20260715
        width = 48
        height = 48
        agents = @('Ада', 'Борин', 'Сайра')
        provider = 'deterministic'
        model = 'scripted-experiment-v1'
    } | ConvertTo-Json -Compress
    $created = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$ApiPort/v1/runs" `
        -Method Post -ContentType 'application/json' -Body $runRequest -TimeoutSec 5
    $firstRun = $created.Content | ConvertFrom-Json
    if ($created.StatusCode -ne 201 -or $firstRun.reused -or -not $firstRun.run_id) {
        throw 'Первое открытие мира не создало ожидаемый запуск.'
    }

    $reopened = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$ApiPort/v1/runs" `
        -Method Post -ContentType 'application/json' -Body $runRequest -TimeoutSec 5
    $secondRun = $reopened.Content | ConvertFrom-Json
    if ($reopened.StatusCode -ne 200 -or -not $secondRun.reused -or $secondRun.run_id -ne $firstRun.run_id) {
        throw 'Повторное открытие не вернуло существующий детерминированный мир.'
    }

    $null = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/v1/runs/$($firstRun.run_id)/controls" `
        -Method Post -ContentType 'application/json' -Body '{"paused":false}' -TimeoutSec 5
    Start-Sleep -Milliseconds 750
    $state = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/v1/runs/$($firstRun.run_id)/state" -TimeoutSec 5
    if ($state.state.processed_events -le 0) {
        throw 'После старта мир не начал обрабатываться.'
    }
    $observer = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/v1/runs/$($firstRun.run_id)/observer" -TimeoutSec 5
    if (
        $observer.agents.Count -ne 3 -or
        $observer.events.Count -le 0 -or
        $observer.run.scenario -ne 'Остров: три агента, семь дней'
    ) {
        throw 'Открытый мир не вернул ожидаемую карту и агентов.'
    }
    Write-Output "Smoke запуска пройден: API $ApiPort, UI $UiPort, живой мир открыт."
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
