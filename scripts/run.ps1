param(
    [switch]$Api,
    [int]$Events = 1000,
    [int]$Seed = 42,
    [ValidateRange(1, 100)]
    [int]$Agents = 3
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { 'python' }
$env:PYTHONPATH = Join-Path $Root 'src'

if ($Api) {
    & $Python -m ai_society.cli serve
} else {
    & $Python -m ai_society.cli run --seed $Seed --events $Events --agents $Agents
}

if ($LASTEXITCODE -ne 0) {
    throw "AI Society command failed with exit code $LASTEXITCODE"
}
