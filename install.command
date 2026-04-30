#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${ROOT_DIR}"

chmod +x build_and_install_app.sh
./build_and_install_app.sh

open -a "Wow Parser"

echo
echo "Installation finished. You can close this window."
read -r -p "Press Enter to exit..."
