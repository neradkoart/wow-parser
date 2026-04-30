#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(tr -d '[:space:]' < "${ROOT_DIR}/VERSION" 2>/dev/null || echo "1.0.0")"
OUT_DIR="${ROOT_DIR}/dist"
STAGE_DIR="${OUT_DIR}/wow-parser-portable"
ARCHIVE_PATH="${OUT_DIR}/wow-parser-portable-v${VERSION}.tar.gz"

mkdir -p "${OUT_DIR}"
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}"

copy_file() {
  local src="$1"
  if [[ -f "${ROOT_DIR}/${src}" ]]; then
    cp "${ROOT_DIR}/${src}" "${STAGE_DIR}/${src}"
  fi
}

copy_dir() {
  local src="$1"
  if [[ -d "${ROOT_DIR}/${src}" ]]; then
    cp -R "${ROOT_DIR}/${src}" "${STAGE_DIR}/${src}"
  fi
}

echo "[pack] Stage portable bundle: ${STAGE_DIR}"
copy_file "app_ui.py"
copy_file "unified_app.py"
copy_file "wow_urls_fetcher.py"
copy_file "urls_splitter.py"
copy_file "parse_vk.py"
copy_file "tiktok_parser_grouped.py"
copy_file "youtube_shorts_parser_grouped.py"
copy_file "dzen_parser_grouped.py"
copy_file "requirements.txt"
copy_file "VERSION"
copy_file "README.md"
copy_dir "src"
copy_file "run.sh"
copy_file "build_and_install_app.sh"
copy_file "install.command"
copy_file "favicon.png"

# Optional runtime helper files if they exist.
copy_file "vk_token.txt"
copy_file "wowData.txt"
copy_file "urls.txt"

# Ensure launch scripts are executable after extraction.
chmod +x "${STAGE_DIR}/run.sh" 2>/dev/null || true
chmod +x "${STAGE_DIR}/build_and_install_app.sh" 2>/dev/null || true
chmod +x "${STAGE_DIR}/install.command" 2>/dev/null || true

echo "[pack] Create archive: ${ARCHIVE_PATH}"
tar -czf "${ARCHIVE_PATH}" -C "${OUT_DIR}" "wow-parser-portable"

echo "[pack] Done"
echo "[pack] Archive: ${ARCHIVE_PATH}"
echo "[pack] On target Mac:"
echo "  1) tar -xzf $(basename "${ARCHIVE_PATH}")"
echo "  2) cd wow-parser-portable"
echo "  3) chmod +x run.sh build_and_install_app.sh"
echo "  4) ./build_and_install_app.sh   # build + install .app"
echo "     or ./run.sh                  # run without install"
echo "     or double-click install.command in Finder"
