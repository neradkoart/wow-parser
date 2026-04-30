param(
    [string]$PythonBin = "py -3.14",
    [string]$VenvDir = ".venv-build-win",
    [string]$AppVersion = ""
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $PSCommandPath
$ProjectRoot = Split-Path -Parent $ScriptRoot
Set-Location $ProjectRoot

Write-Host "[1/5] Create virtualenv: $VenvDir"
Invoke-Expression "$PythonBin -m venv $VenvDir"

$Py = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "[2/5] Install dependencies"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r requirements.txt
& $Py -m playwright install chromium

Write-Host "[3/5] Build app (onedir)"
& $Py -m PyInstaller --noconfirm --windowed --name "Wow Parser" entrypoints/app_ui.py

Write-Host "[4/5] Build installer with Inno Setup"
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    throw "Inno Setup not found: $iscc. Install Inno Setup 6."
}

if (-not $AppVersion) {
    if (Test-Path "VERSION") {
        $AppVersion = (Get-Content "VERSION" -Raw).Trim()
    } else {
        $AppVersion = "1.0.0"
    }
}

& $iscc "/DMyAppVersion=$AppVersion" "scripts\windows-installer.iss"

Write-Host "[5/5] Done"
Write-Host ("Installer: dist\wow-parser-windows-installer-v{0}.exe" -f $AppVersion)
