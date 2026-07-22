$ErrorActionPreference = "Stop"

function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step завершился с кодом $LASTEXITCODE"
    }
}

function Get-CodeSigningCertificates {
    $store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
        "My", [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
    )
    try {
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
        @($store.Certificates) | Where-Object {
            $eku = $_.Extensions | Where-Object {
                $_ -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]
            }
            $eku.EnhancedKeyUsages.Value -contains "1.3.6.1.5.5.7.3.3"
        }
    } finally {
        $store.Close()
    }
}

python -m pip install -e ".[dev]"
Assert-NativeSuccess "Установка зависимостей"
python scripts\generate_compliance.py
Assert-NativeSuccess "Генерация SBOM и лицензий"
python scripts\generate_compliance.py --check
Assert-NativeSuccess "Проверка лицензионного комплекта"
python -m pytest
Assert-NativeSuccess "Unit-тесты"

$signingCertificate = if ($env:DFI_CERTIFICATE_THUMBPRINT) {
    Get-CodeSigningCertificates | Where-Object {
        $_.Thumbprint -eq $env:DFI_CERTIFICATE_THUMBPRINT -and $_.HasPrivateKey
    } | Select-Object -First 1
} else {
    Get-CodeSigningCertificates | Where-Object {
        $_.Subject -eq "CN=Amirkhan Smagulov" -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date)
    } | Sort-Object NotAfter -Descending | Select-Object -First 1
}

python -m PyInstaller --noconfirm --clean --distpath build-tools --workpath build\tool-runner DocumentForensicToolRunner.spec
Assert-NativeSuccess "Сборка адаптера инструментов"
if ($signingCertificate) {
    & .\sign-build.ps1 -CertificateThumbprint $signingCertificate.Thumbprint `
        -Targets @("build-tools\DocumentForensicToolRunner.exe")
} else {
    Write-Warning "Сертификат Amirkhan Smagulov не найден: адаптер останется без подписи."
}

python -m PyInstaller --noconfirm --clean DocumentForensicInspector.spec
Assert-NativeSuccess "Сборка приложения"
if ($signingCertificate) {
    & .\sign-build.ps1 -CertificateThumbprint $signingCertificate.Thumbprint `
        -Targets @("dist\DocumentForensicInspector\DocumentForensicInspector.exe")
} else {
    Write-Warning "Сертификат Amirkhan Smagulov не найден: EXE останется без подписи."
}

python scripts\create_public_source_archive.py
Assert-NativeSuccess "Публичный архив исходного кода"

$isccCommand = Get-Command iscc.exe -ErrorAction SilentlyContinue
$isccPath = if ($isccCommand) {
    $isccCommand.Source
} elseif (Test-Path "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") {
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
} else {
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
if (Test-Path $isccPath) {
    & $isccPath "installer\DocumentForensicInspector.iss"
    Assert-NativeSuccess "Сборка установщика"
    if ($signingCertificate) {
        & .\sign-build.ps1 -CertificateThumbprint $signingCertificate.Thumbprint `
            -Targets @("dist\DocumentForensicInspector-Setup-0.4.2.exe")
    }
} else {
    Write-Warning "Inno Setup не найден: создан portable EXE, установщик не скомпилирован."
}

python scripts\audit_public_release.py
Assert-NativeSuccess "Аудит публичного релиза"

Write-Host "Build ready: dist\DocumentForensicInspector\DocumentForensicInspector.exe"
Write-Host "Installer: dist\DocumentForensicInspector-Setup-0.4.2.exe"
Write-Host "Public source: dist\DocumentForensicInspector-Source-0.4.2.zip"
