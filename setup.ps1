$ErrorActionPreference = "Stop"
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Python 3.12+ is required." }
    }
    & ".venv\Scripts\python.exe" -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    Write-Host "Ready. Open Launch.vbs or run .\run.ps1"
} finally {
    Pop-Location
}
