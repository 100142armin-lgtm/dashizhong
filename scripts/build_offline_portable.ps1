[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RuntimeSource,
    [string]$OutputRoot = "",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $repoRoot "offline-release"
}
if (-not $Version) {
    $Version = (Get-Content -Raw -LiteralPath (Join-Path $repoRoot "VERSION")).Trim()
}
$runtimeSourcePath = [IO.Path]::GetFullPath($RuntimeSource)
$outputRootPath = [IO.Path]::GetFullPath($OutputRoot)
$portableRoot = Join-Path $outputRootPath "Clock-Alarm-$Version-portable"

if (-not (Test-Path -LiteralPath (Join-Path $runtimeSourcePath "python314.dll"))) {
    throw "Runtime source is missing python314.dll: $runtimeSourcePath"
}
$requiredMediaRuntime = @(
    "lib\PyQt6\QtMultimedia.pyd",
    "lib\PyQt6\QtMultimediaWidgets.pyd",
    "lib\PyQt6\QtNetwork.pyd",
    "lib\PyQt6\Qt6\bin\Qt6Multimedia.dll",
    "lib\PyQt6\Qt6\plugins\multimedia\ffmpegmediaplugin.dll"
)
$missingMediaRuntime = @(
    $requiredMediaRuntime | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $runtimeSourcePath $_))
    }
)
if ($missingMediaRuntime.Count -gt 0) {
    throw "Runtime source cannot launch the video player; missing: $($missingMediaRuntime -join ', ')"
}
if (Test-Path -LiteralPath $portableRoot) {
    throw "Output already exists; choose a fresh OutputRoot: $portableRoot"
}

New-Item -ItemType Directory -Path $portableRoot | Out-Null
$runtimeOut = New-Item -ItemType Directory -Path (Join-Path $portableRoot "runtime")
$appOut = New-Item -ItemType Directory -Path (Join-Path $portableRoot "app")

Copy-Item -LiteralPath (Join-Path $runtimeSourcePath "lib") -Destination $runtimeOut.FullName -Recurse
Copy-Item -LiteralPath (Join-Path $runtimeSourcePath "share") -Destination $runtimeOut.FullName -Recurse -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $runtimeSourcePath "PyQt6.uic.widget-plugins") -Destination $runtimeOut.FullName -Recurse -ErrorAction SilentlyContinue
Copy-Item -LiteralPath (Join-Path $runtimeSourcePath "python3.dll") -Destination $runtimeOut.FullName
Copy-Item -LiteralPath (Join-Path $runtimeSourcePath "python314.dll") -Destination $runtimeOut.FullName
Copy-Item -LiteralPath (Join-Path $runtimeSourcePath "frozen_application_license.txt") -Destination $runtimeOut.FullName -ErrorAction SilentlyContinue

# The donor runtime was produced from a developer environment. Build tooling is
# not executable application functionality and must not ship in the candidate.
$buildOnlyDirectories = @(
    "_distutils_hack", "altgraph", "PyInstaller", "setuptools", "wheel", "win32ctypes"
)
foreach ($name in $buildOnlyDirectories) {
    $candidate = Join-Path $runtimeOut.FullName "lib\$name"
    if (Test-Path -LiteralPath $candidate) {
        Remove-Item -LiteralPath $candidate -Recurse -Force
    }
}

$appFiles = @(
    "alarm_sounds.py", "autostart.py", "bookmarks_vault.py", "bookmarks_browser_bridge.py", "bookmarks_ui.py", "cleaner.py", "hotkeys.py", "main.py",
    "media_player_ui.py", "productivity.py", "recorder_ui.py", "screen_recorder.py",
    "screenshot_app.py", "settings_ui.py", "simple_boards.py", "skin.py", "storage.py",
    "theme.py", "world_clock_ui.py", "logo.ico", "logo.png", "VERSION"
)
foreach ($name in $appFiles) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $name) -Destination $appOut.FullName
}
Copy-Item -LiteralPath (Join-Path $repoRoot "assets") -Destination $appOut.FullName -Recurse

$zipPath = Join-Path $runtimeOut.FullName "lib\library.zip"
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$bannedModules = @(
    "__startup__.pyc",
    "alarm_sounds.pyc", "autostart.pyc", "cleaner.pyc", "cleaner_ui.pyc",
    "download_queue.pyc", "gdrive_client.pyc", "hotkeys.pyc", "hub_ui.pyc",
    "lan_share.pyc", "lan_ui.pyc", "lyrics_engine.pyc", "lyrics_ui.pyc",
    "media_player_ui.pyc", "p2p_transfer.pyc", "p2p_ui.pyc", "productivity.pyc",
    "recorder_ui.pyc", "screen_recorder.pyc", "screenshot_app.pyc", "screenshot_ui.pyc",
    "simple_boards.pyc", "skin.pyc", "storage.pyc", "theme.pyc", "ui_theme.pyc",
    "updater.pyc", "voice.pyc", "world_clock_ui.pyc", "BUILD_CONSTANTS.pyc",
    "pefile.pyc"
)
$archive = [IO.Compression.ZipFile]::Open($zipPath, [IO.Compression.ZipArchiveMode]::Update)
try {
    foreach ($entry in @($archive.Entries)) {
        $isLegacyNamedBootstrap = $entry.FullName -match '^__(?:init|main)__[a-z]+\.pyc$'
        if (($bannedModules -contains $entry.FullName) -or $isLegacyNamedBootstrap) {
            $entry.Delete()
        }
    }
} finally {
    $archive.Dispose()
}

$compiler = "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $compiler)) {
    throw "C# compiler not found: $compiler"
}
$iconArg = "/win32icon:$(Join-Path $repoRoot 'logo.ico')"
$outputArg = "/out:$(Join-Path $portableRoot 'Clock-Alarm.exe')"
$sourceFile = Join-Path $repoRoot "launcher\ClockAlarmLauncher.cs"
& $compiler /nologo /target:winexe /platform:x64 /optimize+ $iconArg $outputArg $sourceFile
if ($LASTEXITCODE -ne 0) {
    throw "Launcher compilation failed with exit code $LASTEXITCODE"
}

$remaining = @()
$check = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $remaining = @(
        $check.Entries |
            Where-Object {
                ($bannedModules -contains $_.FullName) -or
                ($_.FullName -match '^__(?:init|main)__[a-z]+\.pyc$')
            } |
            ForEach-Object FullName
    )
} finally {
    $check.Dispose()
}
if ($remaining.Count -gt 0) {
    throw "Removed-feature modules remain in library.zip: $($remaining -join ', ')"
}

$releaseZip = Join-Path $outputRootPath "Clock-Alarm-$Version-windows-portable.zip"
$sevenZip = "C:\Program Files\7-Zip\7z.exe"
if (Test-Path -LiteralPath $sevenZip) {
    Push-Location $outputRootPath
    try {
        & $sevenZip a -tzip -mx=9 -mmt=on $releaseZip (Split-Path -Leaf $portableRoot) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "7-Zip failed with exit code $LASTEXITCODE"
        }
    } finally {
        Pop-Location
    }
} else {
    Compress-Archive -LiteralPath $portableRoot -DestinationPath $releaseZip -CompressionLevel Optimal
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $releaseZip).Hash.ToLowerInvariant()
"$hash  $(Split-Path -Leaf $releaseZip)" | Set-Content -LiteralPath "$releaseZip.sha256" -Encoding ascii

[pscustomobject]@{
    PortableRoot = $portableRoot
    Zip = $releaseZip
    Sha256 = $hash
}
