param(
    [Parameter(Mandatory = $true)]
    [string]$Model,
    [string]$EmbeddingModel,
    [switch]$NoStructuredOutput
)

$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
$Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { 'python' }
$env:PYTHONPATH = Join-Path $Root 'src'

$Arguments = @('-m', 'ai_society.cli', 'ollama-smoke', '--model', $Model)
if ($EmbeddingModel) {
    $Arguments += @('--embedding-model', $EmbeddingModel)
}
if ($NoStructuredOutput) {
    $Arguments += '--no-structured-output'
}

& $Python @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "Ollama smoke failed with exit code $LASTEXITCODE"
}
