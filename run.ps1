$ErrorActionPreference = "Stop"
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Local Python environment is missing. Run setup.ps1 once."
}
Push-Location -LiteralPath $PSScriptRoot
try {
    & $pythonPath -m app.main @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
