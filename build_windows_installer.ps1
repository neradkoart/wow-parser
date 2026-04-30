param(
    [string]$PythonBin = "py -3.14",
    [string]$VenvDir = ".venv-build-win",
    [string]$AppVersion = ""
)

$RootDir = Split-Path -Parent $PSCommandPath
$Target = Join-Path $RootDir "scripts/build_windows_installer.ps1"

& $Target -PythonBin $PythonBin -VenvDir $VenvDir -AppVersion $AppVersion
exit $LASTEXITCODE
