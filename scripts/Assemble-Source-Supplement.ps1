$ErrorActionPreference = 'Stop'
$sourceRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Get-Content -LiteralPath (Join-Path $sourceRoot 'SUPPLEMENT-PARTS.json') -Raw | ConvertFrom-Json
function Safe-Child([string]$Name) {
    if ([IO.Path]::GetFileName($Name) -ne $Name) { throw "Invalid file name: $Name" }
    $resolved = [IO.Path]::GetFullPath((Join-Path $sourceRoot $Name))
    if (-not $resolved.StartsWith($sourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside source folder' }
    return $resolved
}
$outputPath = Safe-Child $manifest.archive
if (Test-Path -LiteralPath $outputPath) {
    if ((Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash -eq $manifest.sha256) {
        Write-Output "Already assembled and verified: $outputPath"
        exit 0
    }
    throw 'An existing archive has a different checksum. Move it aside before retrying.'
}
foreach ($part in $manifest.parts) {
    $partPath = Safe-Child $part.name
    if ((Get-Item -LiteralPath $partPath).Length -ne $part.bytes -or (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash -ne $part.sha256) {
        throw "Missing, incomplete or damaged part: $($part.name)"
    }
}
$temporaryPath = Safe-Child ($manifest.archive + '.' + [guid]::NewGuid().ToString('N') + '.assembling')
$destination = [IO.File]::Open($temporaryPath, [IO.FileMode]::CreateNew)
try {
    foreach ($part in $manifest.parts) {
        $sourceStream = [IO.File]::OpenRead((Safe-Child $part.name))
        try { $sourceStream.CopyTo($destination) } finally { $sourceStream.Dispose() }
    }
} finally { $destination.Dispose() }
if ((Get-FileHash -LiteralPath $temporaryPath -Algorithm SHA256).Hash -ne $manifest.sha256) {
    throw 'Assembled archive checksum differs. The temporary file was retained for inspection.'
}
Move-Item -LiteralPath $temporaryPath -Destination $outputPath
Write-Output "Assembled and verified: $outputPath"
