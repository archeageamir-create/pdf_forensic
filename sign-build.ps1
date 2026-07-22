param(
    [string]$CertificateThumbprint = "",
    [string[]]$Targets = @(),
    [string]$PublisherName = "Amirkhan Smagulov",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

if (-not $Targets) {
    $Targets = @(
        "build-tools\DocumentForensicToolRunner.exe"
        "dist\DocumentForensicInspector\DocumentForensicInspector.exe"
        "dist\DocumentForensicInspector-Setup-0.4.2.exe"
    ) | Where-Object { Test-Path $_ }
}
if (-not $Targets) {
    throw "Собранные файлы для подписи не найдены."
}

$store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
    "My", [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
)
$store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
$certificates = @($store.Certificates) | Where-Object {
    $eku = $_.Extensions | Where-Object {
        $_ -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]
    }
    $eku.EnhancedKeyUsages.Value -contains "1.3.6.1.5.5.7.3.3" -and
    $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) -and
    ((-not $CertificateThumbprint -and $_.Subject -eq "CN=$PublisherName") -or
     ($CertificateThumbprint -and $_.Thumbprint -eq $CertificateThumbprint))
} | Sort-Object NotAfter -Descending
$store.Close()
$certificate = $certificates | Select-Object -First 1
if (-not $certificate) {
    throw "Подходящий сертификат подписи кода не найден в Cert:\CurrentUser\My."
}

foreach ($target in $Targets) {
    $resolvedTarget = (Resolve-Path -LiteralPath $target).Path
    $parameters = @{
        LiteralPath = $resolvedTarget
        Certificate = $certificate
        HashAlgorithm = "SHA256"
        IncludeChain = "All"
    }
    if ($TimestampUrl) {
        $parameters.TimestampServer = $TimestampUrl
    }
    $signed = Set-AuthenticodeSignature @parameters
    if (-not $signed.SignerCertificate -or
        $signed.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
        throw "Не удалось добавить Authenticode-подпись: $resolvedTarget ($($signed.StatusMessage))"
    }
    $verified = Get-AuthenticodeSignature -LiteralPath $resolvedTarget
    if (-not $verified.SignerCertificate -or
        $verified.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
        throw "Проверка подписи не пройдена: $resolvedTarget"
    }
    Write-Host "Signed: $resolvedTarget"
    Write-Host "  Publisher: $($verified.SignerCertificate.Subject)"
    Write-Host "  Thumbprint: $($verified.SignerCertificate.Thumbprint)"
    Write-Host "  Local status: $($verified.Status)"
}
