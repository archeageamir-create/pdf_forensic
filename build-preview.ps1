$ErrorActionPreference = "Stop"
$pythonPath = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Run setup.ps1 first." }
function Assert-PreviewStep([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed ($LASTEXITCODE)." }
}
Push-Location -LiteralPath $PSScriptRoot
$previewOriginalPath = $env:PATH
try {
    & $pythonPath scripts\prepare_runtime_dependencies.py --download
    Assert-PreviewStep "Complete standalone tool payload"
    # A native-tools PATH may contain a different icuuc.dll (for example Poppler).
    # Qt needs the Windows ICU API. Let PyInstaller resolve OS libraries from
    # Windows instead of accidentally bundling an unrelated tool's DLLs.
    $previewPythonBase = & $pythonPath -c "import sys; print(sys.base_prefix)"
    Assert-PreviewStep "Python runtime discovery"
    $env:PATH = "$PSScriptRoot\.venv\Scripts;$previewPythonBase;$env:WINDIR\System32;$env:WINDIR"
    & $pythonPath scripts\prepare_preview_build.py
    Assert-PreviewStep "Build inventory"
    & $pythonPath -m PyInstaller --noconfirm --clean --distpath build-tools --workpath build\tool-runner DocumentForensicToolRunner.spec
    Assert-PreviewStep "Tool runner"
    & $pythonPath -m PyInstaller --noconfirm --clean DocumentForensicInspectorPreview.spec
    Assert-PreviewStep "Preview application"
    $env:PATH = $previewOriginalPath
    $previewProbeDirectory = Join-Path $PSScriptRoot (".verification\build-gui-" + [guid]::NewGuid().ToString("N"))
    & $pythonPath scripts\verify_preview_gui.py --output $previewProbeDirectory
    Assert-PreviewStep "Native GUI startup and background queue"
    & $pythonPath scripts\verify_standalone_engines.py --exe dist\DocumentForensicInspectorPreview\DocumentForensicInspectorPreview.exe --output (Join-Path $previewProbeDirectory "standalone-engines")
    Assert-PreviewStep "Every bundled engine, full PDF, media and report export"
    Write-Host "Ready: dist\DocumentForensicInspectorPreview\DocumentForensicInspectorPreview.exe"
} finally {
    $env:PATH = $previewOriginalPath
    Pop-Location
}
