#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python3.14}"
VENV_DIR="${VENV_DIR:-.venv-build}"

echo "[1/4] Создание virtualenv: ${VENV_DIR}"
"${PYTHON_BIN}" -m venv "${VENV_DIR}"

echo "[2/4] Установка зависимостей в virtualenv"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r requirements.txt
"${VENV_DIR}/bin/python" -m playwright install chromium

echo "[3/4] Сборка onefile бинарника"
"${VENV_DIR}/bin/python" -m PyInstaller --onefile --name wow-parser-app entrypoints/app_ui.py

echo "[4/4] Готово"
echo "Бинарник: dist/wow-parser-app"
echo "Для пересборки можно удалить ${VENV_DIR}"
