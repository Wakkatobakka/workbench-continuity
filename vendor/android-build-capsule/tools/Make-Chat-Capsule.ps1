# WAKKA Android Build Capsule. MIT. Windows PowerShell 5.1 or PowerShell 7.
# Creates a private Linux runtime for chat. Does not require Python or Java on this PC.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$CoreRoot = Split-Path -Parent $PSScriptRoot
$PrivateRoot = Join-Path $CoreRoot '.private'
$OutputRoot = Join-Path $CoreRoot 'Private_Capsules'
$Utf8 = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Type -AssemblyName System.Windows.Forms
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-JsonFile([string]$Path, $Value) {
    $Parent = Split-Path -Parent $Path
    [IO.Directory]::CreateDirectory($Parent) | Out-Null
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 30) + "`n", $Utf8)
}

function Join-SafePath([string]$Root, [string]$Relative) {
    $Normalized = $Relative.Replace('\', '/')
    if ($Normalized.StartsWith('/') -or $Normalized.Contains(':') -or
        (($Normalized.Split('/')) -contains '..')) { throw "Unsafe archive path: $Relative" }
    $FullRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $Result = [IO.Path]::GetFullPath((Join-Path $Root $Normalized.Replace('/', '\')))
    if (-not $Result.StartsWith($FullRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path leaves the destination: $Relative"
    }
    return $Result
}

function Expand-VerifiedZip([string]$Archive, [string]$Destination) {
    [IO.Directory]::CreateDirectory($Destination) | Out-Null
    $Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $Total = 0L
        $Seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
        foreach ($Entry in $Zip.Entries) {
            $Total += $Entry.Length
            if ($Total -gt 2000000000) { throw 'Archive exceeds the 2 GB extraction limit.' }
            $Name = $Entry.FullName.Replace('\', '/')
            $Target = Join-SafePath $Destination $Name
            if ($Name.EndsWith('/')) { [IO.Directory]::CreateDirectory($Target) | Out-Null; continue }
            if (-not $Seen.Add($Name)) { throw "Duplicate archive entry: $Name" }
            # Unix symlink mode in ZIP external attributes.
            $Mode = ($Entry.ExternalAttributes -shr 16) -band 0xF000
            if ($Mode -eq 0xA000) { throw "Archive symlink is not accepted: $Name" }
            [IO.Directory]::CreateDirectory((Split-Path -Parent $Target)) | Out-Null
            $Input = $Entry.Open()
            try {
                $Output = [IO.File]::Open($Target, [IO.FileMode]::CreateNew)
                try { $Input.CopyTo($Output) } finally { $Output.Dispose() }
            } finally { $Input.Dispose() }
        }
    } finally { $Zip.Dispose() }
}

function Download-Checked($Record, [string]$Cache) {
    $Target = Join-Path $Cache $Record.filename
    if ((Test-Path -LiteralPath $Target) -and
        ((Get-Item -LiteralPath $Target).Length -eq [long]$Record.size_bytes) -and
        ((Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Record.sha256)) {
        Write-Host "Reusing verified download: $($Record.filename)"
        return $Target
    }
    $Partial = $Target + '.partial'
    if (Test-Path -LiteralPath $Partial) { Remove-Item -LiteralPath $Partial }
    Write-Host "Downloading from Google: $($Record.filename)"
    $Client = New-Object Net.WebClient
    try {
        $Client.Headers.Add('User-Agent', 'WAKKA-Capsule/0.1.0')
        $Client.DownloadFile($Record.url, $Partial)
        $Actual = (Get-FileHash -LiteralPath $Partial -Algorithm SHA256).Hash.ToLowerInvariant()
        if (((Get-Item -LiteralPath $Partial).Length -ne [long]$Record.size_bytes) -or ($Actual -ne $Record.sha256)) {
            throw "Download checksum failed: $($Record.filename)"
        }
        Move-Item -LiteralPath $Partial -Destination $Target -Force
    } finally {
        $Client.Dispose()
        if (Test-Path -LiteralPath $Partial) { Remove-Item -LiteralPath $Partial }
    }
    return $Target
}

function Write-PortableZip([string]$Folder, [string]$Archive) {
    $RootPrefix = [IO.Path]::GetFullPath($Folder).TrimEnd('\') + '\'
    $FolderName = Split-Path -Leaf $Folder
    $Stream = [IO.File]::Open($Archive, [IO.FileMode]::CreateNew)
    $Zip = New-Object IO.Compression.ZipArchive($Stream, [IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        foreach ($File in (Get-ChildItem -LiteralPath $Folder -Recurse -File | Sort-Object FullName)) {
            $Relative = $File.FullName.Substring($RootPrefix.Length).Replace('\', '/')
            $Entry = $Zip.CreateEntry($FolderName + '/' + $Relative, [IO.Compression.CompressionLevel]::Optimal)
            $Input = [IO.File]::OpenRead($File.FullName)
            try {
                $Output = $Entry.Open()
                try { $Input.CopyTo($Output) } finally { $Output.Dispose() }
            } finally { $Input.Dispose() }
        }
    } finally { $Zip.Dispose(); $Stream.Dispose() }
}

$TempRoot = $null
$Runtime = $null
$Finished = $false
try {
    # Only copy the verified public allowlist. Never copy signing keys, logs or personal files.
    $ManifestPath = Join-Path $CoreRoot 'PUBLIC_FILES.sha256.json'
    $Manifest = [IO.File]::ReadAllText($ManifestPath, $Utf8) | ConvertFrom-Json
    foreach ($Property in $Manifest.PSObject.Properties) {
        $Path = Join-SafePath $CoreRoot $Property.Name
        $Hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Hash -ne $Property.Value) { throw "Public core checksum failed: $($Property.Name)" }
    }
    # Fetch and display Google's agreement before SDK archives are downloaded.
    $Client = New-Object Net.WebClient
    try { $XmlText = $Client.DownloadString('https://dl.google.com/android/repository/repository2-3.xml') }
    finally { $Client.Dispose() }
    [xml]$Repository = $XmlText
    $LicenseNode = $Repository.SelectSingleNode("//*[local-name()='license' and @id='android-sdk-license']")
    if ($null -eq $LicenseNode -or [string]::IsNullOrWhiteSpace($LicenseNode.InnerText)) {
        throw 'The official Android SDK agreement could not be read. No SDK was installed.'
    }
    $LicenseText = $LicenseNode.InnerText
    $Form = New-Object Windows.Forms.Form
    $Form.Text = 'Android SDK agreement - personal setup'
    $Form.Size = New-Object Drawing.Size(760, 610)
    $Form.StartPosition = 'CenterScreen'
    $Intro = New-Object Windows.Forms.Label
    $Intro.Text = "This makes a PRIVATE SDK runtime for chat. The public core is shareable; the generated SDK ZIP is not cleared for public distribution. Read Google's agreement below."
    $Intro.Dock = 'Top'; $Intro.Height = 62; $Intro.Padding = New-Object Windows.Forms.Padding(12)
    $Text = New-Object Windows.Forms.TextBox
    $Text.Multiline = $true; $Text.ReadOnly = $true; $Text.ScrollBars = 'Vertical'
    $Text.Dock = 'Fill'; $Text.Text = $LicenseText.Replace("`n", "`r`n")
    $Buttons = New-Object Windows.Forms.FlowLayoutPanel
    $Buttons.Dock = 'Bottom'; $Buttons.Height = 52; $Buttons.FlowDirection = 'RightToLeft'
    $Accept = New-Object Windows.Forms.Button
    $Accept.Text = 'I accept'; $Accept.Width = 110; $Accept.DialogResult = 'OK'
    $Cancel = New-Object Windows.Forms.Button
    $Cancel.Text = 'Cancel'; $Cancel.Width = 110; $Cancel.DialogResult = 'Cancel'
    $Link = New-Object Windows.Forms.Button
    $Link.Text = 'Official terms page'; $Link.Width = 155
    $Link.Add_Click({ Start-Process 'https://developer.android.com/studio/terms' })
    $Buttons.Controls.AddRange(@($Accept, $Cancel, $Link))
    $Form.Controls.Add($Text); $Form.Controls.Add($Intro); $Form.Controls.Add($Buttons)
    $Form.CancelButton = $Cancel
    try { $Decision = $Form.ShowDialog() } finally { $Form.Dispose() }
    if ($Decision -ne [Windows.Forms.DialogResult]::OK) {
        Write-Host 'Cancelled. No SDK archives were downloaded.'
        exit 0
    }
    [IO.Directory]::CreateDirectory($PrivateRoot) | Out-Null
    [IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
    $Cache = Join-Path $PrivateRoot 'downloads'
    [IO.Directory]::CreateDirectory($Cache) | Out-Null
    # Short temporary paths avoid the collector's old long-path packaging problem.
    $TempRoot = Join-Path ([IO.Path]::GetTempPath()) ('ABC_' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    [IO.Directory]::CreateDirectory($TempRoot) | Out-Null
    $Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    # Assemble the full SDK under a short temp path, then export only its ZIP.
    # This avoids expanding deep SDK paths under a long Downloads folder name.
    $Runtime = Join-Path $TempRoot ('WAKKA_Chat_Runtime_' + $Stamp)
    [IO.Directory]::CreateDirectory($Runtime) | Out-Null
    foreach ($Property in $Manifest.PSObject.Properties) {
        $Source = Join-SafePath $CoreRoot $Property.Name
        $Target = Join-SafePath $Runtime $Property.Name
        [IO.Directory]::CreateDirectory((Split-Path -Parent $Target)) | Out-Null
        [IO.File]::Copy($Source, $Target, $false)
    }
    [IO.File]::Copy($ManifestPath, (Join-Path $Runtime 'PUBLIC_FILES.sha256.json'), $false)
    $DownloadManifest = [IO.File]::ReadAllText((Join-Path $CoreRoot 'official-downloads.json'), $Utf8) | ConvertFrom-Json
    $Receipts = @()
    foreach ($Record in $DownloadManifest.archives) {
        $Archive = Download-Checked $Record $Cache
        $Unpack = Join-Path $TempRoot $Record.kind
        Write-Host "Extracting: $($Record.filename)"
        Expand-VerifiedZip $Archive $Unpack
        $Candidate = @(Get-ChildItem -LiteralPath $Unpack -Directory | Where-Object {
            Test-Path -LiteralPath (Join-Path $_.FullName 'source.properties')
        })
        if ($Candidate.Count -ne 1) { throw "Unexpected official archive layout: $($Record.filename)" }
        $Relative = if ($Record.kind -eq 'platform') { 'runtime/sdk/platforms/android-35' } else { 'runtime/sdk/build-tools/35.0.0' }
        $Destination = Join-SafePath $Runtime $Relative
        [IO.Directory]::CreateDirectory((Split-Path -Parent $Destination)) | Out-Null
        Move-Item -LiteralPath $Candidate[0].FullName -Destination $Destination
        $Receipts += [ordered]@{ url = $Record.url; sha256 = $Record.sha256; size_bytes = $Record.size_bytes }
    }
    $Sdk = Join-Path $Runtime 'runtime/sdk'
    [IO.File]::WriteAllText((Join-Path $Sdk 'SDK_LICENSE_FROM_GOOGLE.txt'), $LicenseText, $Utf8)
    $Prefix = [IO.Path]::GetFullPath($Sdk).TrimEnd('\') + '\'
    $Inventory = [ordered]@{}
    Write-Host 'Hashing the runtime files...'
    foreach ($File in (Get-ChildItem -LiteralPath $Sdk -Recurse -File | Sort-Object FullName)) {
        $Name = $File.FullName.Substring($Prefix.Length).Replace('\', '/')
        $Inventory[$Name] = (Get-FileHash -LiteralPath $File.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    Write-JsonFile (Join-Path $Runtime 'runtime/SDK_FILES.sha256.json') $Inventory
    Write-JsonFile (Join-Path $Runtime 'PRIVATE_RUNTIME.json') ([ordered]@{
        distribution = 'private-runtime'; capsule_version = '0.1.0'; created_at = [DateTime]::UtcNow.ToString('o')
        sdk_terms = 'https://developer.android.com/studio/terms'
        sdk_license_accepted_by = 'Person clicking I accept during local Windows setup'
        archives = $Receipts; public_redistribution = 'Not cleared. Do not publish this generated SDK bundle.'
        host_jdk = 'JDK 17+ supplied by the Linux chat host; no JDK bundled'
        contains_project_signing_keys = $false
    })
    $ZipPath = Join-Path $OutputRoot ((Split-Path -Leaf $Runtime) + '.zip')
    Write-Host 'Making the portable chat ZIP with forward-slash paths...'
    Write-PortableZip $Runtime $ZipPath
    $Finished = $true
    Write-Host ''
    Write-Host "READY: $ZipPath"
    Write-Host 'Upload that ZIP with your project in chat. The assistant should read AI_START_HERE.txt first.'
    Write-Host 'Keep this generated SDK ZIP private. Share the original public core ZIP on GitHub.'
    Start-Process explorer.exe -ArgumentList ('/select,"' + $ZipPath + '"')
} catch {
    [IO.Directory]::CreateDirectory($PrivateRoot) | Out-Null
    [IO.File]::WriteAllText((Join-Path $PrivateRoot 'LAST_SETUP_ERROR.txt'), $_.Exception.ToString(), $Utf8)
    Write-Host ("SETUP STOPPED: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'The error is saved in .private/LAST_SETUP_ERROR.txt. Verified downloads will be reused on retry.'
    exit 1
} finally {
    if ($null -ne $TempRoot -and (Test-Path -LiteralPath $TempRoot)) {
        Remove-Item -LiteralPath $TempRoot -Recurse -Force
    }
    if (-not $Finished -and $null -ne $Runtime -and (Test-Path -LiteralPath $Runtime)) {
        Remove-Item -LiteralPath $Runtime -Recurse -Force
    }
}
