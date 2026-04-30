#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv-runtime"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BOOTSTRAP_MARKER="${VENV_DIR}/.bootstrap_done"

echo "[run] Root: ${ROOT_DIR}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "[run] ERROR: Python not found (${PYTHON_BIN}). Install Python 3.11+."
  exit 1
fi

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "[run] Create virtualenv"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

if [[ ! -f "${BOOTSTRAP_MARKER}" ]]; then
  echo "[run] Install dependencies"
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/requirements.txt"
  "${VENV_DIR}/bin/python" -m playwright install chromium
  date > "${BOOTSTRAP_MARKER}"
fi

echo "[run] Start app UI"
cd "${ROOT_DIR}"
exec "${VENV_DIR}/bin/python" "${ROOT_DIR}/app_ui.py"
