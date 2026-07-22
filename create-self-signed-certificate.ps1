param(
    [string]$PublisherName = "Amirkhan Smagulov",
    [int]$ValidityYears = 5,
    [string]$PublicCertificatePath = "signing\Amirkhan-Smagulov-Code-Signing.cer"
)

$ErrorActionPreference = "Stop"
$subject = "CN=$PublisherName"
$store = [System.Security.Cryptography.X509Certificates.X509Store]::new(
    "My", [System.Security.Cryptography.X509Certificates.StoreLocation]::CurrentUser
)
$store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadOnly)
$certificate = @($store.Certificates) | Where-Object {
    $eku = $_.Extensions | Where-Object {
        $_ -is [System.Security.Cryptography.X509Certificates.X509EnhancedKeyUsageExtension]
    }
    $eku.EnhancedKeyUsages.Value -contains "1.3.6.1.5.5.7.3.3" -and
    $_.Subject -eq $subject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date).AddMonths(3)
} | Sort-Object NotAfter -Descending | Select-Object -First 1
$store.Close()

if (-not $certificate) {
    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -FriendlyName "$PublisherName — Document Forensic Inspector Code Signing" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears($ValidityYears)
}

$publicPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $PublicCertificatePath))
$publicDirectory = Split-Path -Parent $publicPath
New-Item -ItemType Directory -Path $publicDirectory -Force | Out-Null
Export-Certificate -Cert $certificate -FilePath $publicPath -Force | Out-Null

foreach ($store in ("Cert:\CurrentUser\Root", "Cert:\CurrentUser\TrustedPublisher")) {
    $exists = Get-ChildItem $store | Where-Object Thumbprint -eq $certificate.Thumbprint
    if (-not $exists) {
        Import-Certificate -FilePath $publicPath -CertStoreLocation $store | Out-Null
    }
}

Write-Host "Code-signing certificate ready."
Write-Host "Subject: $($certificate.Subject)"
Write-Host "Thumbprint: $($certificate.Thumbprint)"
Write-Host "Valid through: $($certificate.NotAfter.ToString('yyyy-MM-dd'))"
Write-Host "Public certificate: $publicPath"
Write-Host "The private key remains in the current-user Windows certificate store and was not exported."
