param(
    [ValidateSet('installer','portable')][string]$Package = 'installer',
    [switch]$LaunchInstaller
)
$ErrorActionPreference = 'Stop'
function Get-Sha256([string]$Path) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $algorithm.Dispose() }
}
try {
    $catalog = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'DOWNLOAD-PARTS.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $record = $catalog.$Package
    if (-not $record -or $record.file -notmatch '^DocumentForensicInspector-(Setup-)?[0-9.]+(-Windows)?\.(exe|zip)$') { throw 'Invalid package record.' }
    $destination = Join-Path $PSScriptRoot $record.file
    $temporary = Join-Path $PSScriptRoot ([Guid]::NewGuid().ToString('N')+'.assembling')
    if (Test-Path -LiteralPath $destination) {
        if ((Get-Sha256 $destination) -ne $record.sha256) {
            throw 'An existing output file has a different checksum. Move it aside before continuing.'
        }
    } else {
        try {
            $output = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
            try {
                foreach ($part in $record.parts) {
                    if ($part.file -notmatch '^[A-Za-z0-9_.-]+\.[0-9]{3}$') { throw 'Invalid part name.' }
                    $source = Join-Path $PSScriptRoot $part.file
                    if (-not (Test-Path -LiteralPath $source)) { throw ('Missing download: '+$part.file) }
                    if ((Get-Item -LiteralPath $source).Length -ne $part.bytes -or (Get-Sha256 $source) -ne $part.sha256) {
                        throw ('Download is incomplete or damaged: '+$part.file)
                    }
                    Write-Host ('Checking and joining '+$part.file)
                    $inputStream = [IO.File]::OpenRead($source)
                    try { $inputStream.CopyTo($output) } finally { $inputStream.Dispose() }
                }
            } finally { $output.Dispose() }
            if ((Get-Item -LiteralPath $temporary).Length -ne $record.bytes -or (Get-Sha256 $temporary) -ne $record.sha256) {
                throw 'The assembled package checksum does not match.'
            }
            Move-Item -LiteralPath $temporary -Destination $destination
        } finally {
            if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
        }
    }
    Write-Host ('Ready: '+$destination)
    if ($LaunchInstaller) {
        if ($Package -ne 'installer' -or [IO.Path]::GetExtension($destination) -ne '.exe') { throw 'Only the installer can be launched.' }
        Start-Process -FilePath $destination -Wait
    }
} catch {
    Write-Error $_
    exit 1
}
