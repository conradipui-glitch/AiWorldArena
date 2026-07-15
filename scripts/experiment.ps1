param(
    [ValidateSet('scripted', 'natural', 'controlled')]
    [string]$Mode = 'scripted',
    [string[]]$Models = @(),
    [long]$Seed = 20260715,
    [ValidateSet(48, 64)]
    [int]$Size = 48,
    [string]$Name = 'three-agents-seven-days'
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { 'python' }
$env:PYTHONPATH = Join-Path $Root 'src'

$Arguments = @(
    '-m', 'ai_society.cli', 'experiment',
    '--mode', $Mode,
    '--seed', $Seed,
    '--size', $Size,
    '--name', $Name
)
if ($Models.Count -gt 0) {
    $Arguments += '--models'
    $Arguments += $Models
}

& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Experimental MVP failed with exit code $LASTEXITCODE"
}
