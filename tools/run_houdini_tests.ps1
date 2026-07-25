param(
    [string]$HoudiniRoot = "C:\Program Files\Side Effects Software\Houdini 21.0.729"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$hython = Join-Path $HoudiniRoot "bin\hython.exe"
if (-not (Test-Path -LiteralPath $hython)) {
    throw "hython.exe was not found: $hython"
}

$testPrefsBase = Join-Path ([IO.Path]::GetTempPath()) "hcq-houdini-test-prefs"
$expandedPrefs = Join-Path $testPrefsBase "houdini21.0"
New-Item -ItemType Directory -Path $expandedPrefs -Force | Out-Null

$env:HOUDINI_USER_PREF_DIR = Join-Path $testPrefsBase "houdini__HVER__"
$env:HOUDINI_PACKAGE_DIR = (Resolve-Path (Join-Path $repoRoot "packages")).Path

& $hython (Join-Path $repoRoot "tools\test_hcq_houdini.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$env:QT_QPA_PLATFORM = "offscreen"
& $hython (Join-Path $repoRoot "tools\test_hcq_ui.py")
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
