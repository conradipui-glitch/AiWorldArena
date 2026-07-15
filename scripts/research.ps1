param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArguments
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { 'python' }
$env:PYTHONPATH = Join-Path $Root 'src'

if ($CliArguments.Count -eq 0) {
    throw "Укажите исследовательскую команду, например: catalog-experiments."
}

& $Python -m ai_society.cli @CliArguments
if ($LASTEXITCODE -ne 0) {
    throw "Исследовательская команда завершилась с кодом $LASTEXITCODE"
}
