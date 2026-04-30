#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${ROOT_DIR}/.venv-builder"
APP_NAME="Wow Parser"
APP_PATH="${ROOT_DIR}/dist/${APP_NAME}.app"
INSTALL_DIR="${INSTALL_DIR:-/Applications}"
INSTALL_PATH="${INSTALL_DIR}/${APP_NAME}.app"

echo "[builder] Root: ${ROOT_DIR}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "[builder] ERROR: Python not found (${PYTHON_BIN}). Install Python 3.11+."
  exit 1
fi

echo "[builder] Create builder virtualenv"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"

echo "[builder] Install dependencies"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/requirements.txt"
"${VENV_DIR}/bin/python" -m playwright install chromium

echo "[builder] Build .app via PyInstaller"
rm -rf "${ROOT_DIR}/build/${APP_NAME}" "${APP_PATH}"
"${VENV_DIR}/bin/python" -m PyInstaller --noconfirm --windowed --name "${APP_NAME}" "${ROOT_DIR}/entrypoints/app_ui.py"

if [[ ! -d "${APP_PATH}" ]]; then
  echo "[builder] ERROR: app bundle not found at ${APP_PATH}"
  exit 1
fi

echo "[builder] Install app to ${INSTALL_DIR}"
if [[ -d "${INSTALL_PATH}" ]]; then
  rm -rf "${INSTALL_PATH}"
fi

if [[ -w "${INSTALL_DIR}" ]]; then
  cp -R "${APP_PATH}" "${INSTALL_PATH}"
else
  sudo cp -R "${APP_PATH}" "${INSTALL_PATH}"
fi

echo "[builder] Done"
echo "[builder] Installed: ${INSTALL_PATH}"
echo "[builder] Run: open -a \"${APP_NAME}\""
