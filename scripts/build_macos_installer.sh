#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python3.14}"
VENV_DIR="${VENV_DIR:-.venv-build}"
APP_NAME="Wow Parser"
APP_BUNDLE="dist/${APP_NAME}.app"
APP_VERSION="${APP_VERSION:-$(tr -d '[:space:]' < VERSION 2>/dev/null || echo 1.0.0)}"
TARGET_ARCH="${TARGET_ARCH:-native}"
ARCH_SUFFIX="${TARGET_ARCH}"
if [[ "${TARGET_ARCH}" == "native" ]]; then
  ARCH_SUFFIX="$(uname -m)"
fi
DMG_NAME="wow-parser-macos-installer-${ARCH_SUFFIX}-v${APP_VERSION}.dmg"
DMG_PATH="dist/${DMG_NAME}"

echo "[1/6] Создание virtualenv: ${VENV_DIR}"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"

echo "[2/6] Установка зависимостей"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r requirements.txt
"${VENV_DIR}/bin/python" -m playwright install chromium

echo "[3/6] Сборка .app через PyInstaller"
rm -rf "build/${APP_NAME}" "${APP_BUNDLE}"
if [[ "${TARGET_ARCH}" == "native" ]]; then
  "${VENV_DIR}/bin/python" -m PyInstaller --noconfirm --windowed --name "${APP_NAME}" entrypoints/app_ui.py
else
  "${VENV_DIR}/bin/python" -m PyInstaller --noconfirm --windowed --target-arch "${TARGET_ARCH}" --name "${APP_NAME}" entrypoints/app_ui.py
fi

echo "[4/6] Подготовка DMG содержимого"
rm -rf dist/dmg
mkdir -p dist/dmg
cp -R "${APP_BUNDLE}" dist/dmg/
ln -s /Applications dist/dmg/Applications

echo "[5/6] Сборка DMG"
hdiutil create -volname "${APP_NAME}" -srcfolder dist/dmg -ov -format UDZO "${DMG_PATH}"

echo "[6/6] Готово"
echo "Приложение: ${APP_BUNDLE}"
echo "Установщик: ${DMG_PATH}"
