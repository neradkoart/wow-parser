param(
    [string]$PythonBin = "py -3.14",
    [string]$VenvDir = ".venv-build-win",
    [string]$AppVersion = ""
)

$ErrorActionPreference = "Stop"

Write-Host "[1/5] Создание virtualenv: $VenvDir"
Invoke-Expression "$PythonBin -m venv $VenvDir"

$Py = Join-Path $VenvDir "Scripts\python.exe"

Write-Host "[2/5] Установка зависимостей"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r requirements.txt
& $Py -m playwright install chromium

Write-Host "[3/5] Сборка приложения (onedir)"
& $Py -m PyInstaller --noconfirm --windowed --name "Wow Parser" app_ui.py

Write-Host "[4/5] Сборка инсталлятора через Inno Setup"
$iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    throw "Не найден Inno Setup: $iscc. Установи Inno Setup 6."
}

if (-not $AppVersion) {
    if (Test-Path "VERSION") {
        $AppVersion = (Get-Content "VERSION" -Raw).Trim()
    } else {
        $AppVersion = "1.0.0"
    }
}

& $iscc "/DMyAppVersion=$AppVersion" "windows-installer.iss"

Write-Host "[5/5] Готово"
Write-Host "Инсталлятор: dist\wow-parser-windows-installer-v$AppVersion.exe"
