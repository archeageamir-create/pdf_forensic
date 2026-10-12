$ErrorActionPreference = "Stop"
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Run setup.ps1 first." }
function Assert-Step([string]$Step) { if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)." } }
Push-Location -LiteralPath $PSScriptRoot
$originalBuildPath = $env:PATH
try {
    & $pythonPath scripts\prepare_runtime_dependencies.py --download
    Assert-Step "Runtime payload"
    & $pythonPath scripts\verify_source_delivery.py
    Assert-Step "Corresponding source delivery"
    & $pythonPath -m pytest -q
    Assert-Step "Tests"
    & $pythonPath scripts\prepare_release.py
    Assert-Step "Release inventory"
    $pythonBase = & $pythonPath -c "import sys; print(sys.base_prefix)"
    Assert-Step "Python discovery"
    $env:PATH = "$PSScriptRoot\.venv\Scripts;$pythonBase;$env:WINDIR\System32;$env:WINDIR"
    & $pythonPath -m PyInstaller --noconfirm --clean --distpath build-tools --workpath build\tool-runner DocumentForensicToolRunner.spec
    Assert-Step "Tool runner"
    & $pythonPath -m PyInstaller --noconfirm --clean DocumentForensicInspector.spec
    Assert-Step "Application"
    $env:PATH = $originalBuildPath
    $probe = Join-Path $PSScriptRoot (".verification\release-" + [guid]::NewGuid().ToString("N"))
    & $pythonPath scripts\verify_preview_gui.py --exe dist\DocumentForensicInspector\DocumentForensicInspector.exe --output $probe
    Assert-Step "Native GUI"
    & $pythonPath scripts\verify_standalone_engines.py --exe dist\DocumentForensicInspector\DocumentForensicInspector.exe --output (Join-Path $probe "engines")
    Assert-Step "Standalone engines"
    & $pythonPath scripts\create_public_source_archive.py
    Assert-Step "Source archive"
    $compiler = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path -LiteralPath $compiler)) { $compiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
    if (-not (Test-Path -LiteralPath $compiler)) { throw "Install Inno Setup 6 to build the installer." }
    & $compiler installer\DocumentForensicInspector.iss
    Assert-Step "Installer"
    & $pythonPath scripts\package_preview.py --release
    Assert-Step "Portable archive"
    & $pythonPath scripts\audit_public_release.py
    Assert-Step "Release audit"
} finally {
    $env:PATH = $originalBuildPath
    Pop-Location
}
