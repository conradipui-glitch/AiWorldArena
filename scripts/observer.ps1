param(
    [ValidateRange(1024, 65535)]
    [int]$ApiPort = 8000,
    [ValidateRange(1024, 65535)]
    [int]$UiPort = 5173,
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$UiUrl = "http://127.0.0.1:$UiPort"

function Test-Listener {
    param([int]$Port)

    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Test-ApiHealth {
    param([int]$Port)

    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
        return $Health.status -eq 'ok'
    } catch {
        return $false
    }
}

$ApiAlreadyListening = Test-Listener -Port $ApiPort
$UiAlreadyListening = Test-Listener -Port $UiPort
if ($ApiAlreadyListening -or $UiAlreadyListening) {
    if ($ApiAlreadyListening -and $UiAlreadyListening -and (Test-ApiHealth -Port $ApiPort)) {
        Write-Output "Наблюдатель уже готов: $UiUrl"
        if ($OpenBrowser) {
            Start-Process $UiUrl
        }
        return
    }

    $OccupiedPorts = @()
    if ($ApiAlreadyListening) {
        $OccupiedPorts += $ApiPort
    }
    if ($UiAlreadyListening) {
        $OccupiedPorts += $UiPort
    }
    throw "Порты $($OccupiedPorts -join ', ') уже заняты, но готовый наблюдатель не найден. Освободите их или задайте AIWORLD_API_PORT и AIWORLD_UI_PORT."
}

$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = 'python'
}
$env:PYTHONPATH = Join-Path $Root 'src'

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm не найден. Установите Node.js LTS и повторите запуск."
}
if (-not (Test-Path -LiteralPath (Join-Path $Root 'client\node_modules'))) {
    throw "Клиент ещё не подготовлен. Выполните один раз 'Set-Location client; npm ci'."
}

$Work = Join-Path $Root 'work'
New-Item -ItemType Directory -Force -Path $Work | Out-Null

$ApiProcess = $null
$UiProcess = $null
try {
    # Vite reads this only for its local development proxy. It keeps a
    # non-default launcher pair connected to its matching API instance.
    $env:AI_SOCIETY_API_PORT = $ApiPort

    $ApiProcess = Start-Process -FilePath $Python `
        -ArgumentList "-m uvicorn ai_society.api.app:app --host 127.0.0.1 --port $ApiPort" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Work 'observer-api.log') `
        -RedirectStandardError (Join-Path $Work 'observer-api.err.log') `
        -PassThru

    $UiProcess = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList "/c npm run dev -- --host 127.0.0.1 --port $UiPort" `
        -WorkingDirectory (Join-Path $Root 'client') `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Work 'observer-ui.log') `
        -RedirectStandardError (Join-Path $Work 'observer-ui.err.log') `
        -PassThru

    $Deadline = (Get-Date).AddSeconds(20)
    $Ready = $false
    while ((Get-Date) -lt $Deadline) {
        try {
            $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 2
            $UiReady = Test-NetConnection -ComputerName '127.0.0.1' -Port $UiPort -InformationLevel Quiet -WarningAction SilentlyContinue
            if ($Health.status -eq 'ok' -and $UiReady) {
                $Ready = $true
                break
            }
        } catch {
            # The child processes are still initializing. The loop has a fixed deadline.
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $Ready) {
        throw "Наблюдатель не стал доступен за 20 секунд. Проверьте файлы work\observer-*.log."
    }
    Write-Output "Наблюдатель готов: $UiUrl"
    if ($OpenBrowser) {
        Start-Process $UiUrl
    }
} catch {
    foreach ($Process in @($ApiProcess, $UiProcess)) {
        if ($null -ne $Process -and -not $Process.HasExited) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    throw
}
