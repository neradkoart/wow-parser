# WOW Parser Unified App

Единое приложение для парсинга и отчетов по платформам:

- VK
- TikTok
- YouTube
- Dzen
- Pinterest

Пайплайн:

1. (опционально) загрузка ссылок из WOW API (`wow_urls_fetcher.py`);
2. нормализация и разбиение ссылок (`urls_splitter.py`);
3. параллельный парсинг соцсетей;
4. генерация отчетов (`report.html`, `report.json` + отдельные страницы по платформам).

## Структура проекта

- `src/ui/` — веб-интерфейс приложения
- `src/core/` — оркестратор пайплайна, сплиттер ссылок, WOW fetcher
- `src/parsers/` — парсеры по платформам
- корневые `*.py` файлы — легковесные точки входа (совместимость со старыми скриптами сборки)

---

## Быстрый старт для человека "с улицы" (macOS)

Ниже самый понятный путь: скачать архив, распаковать, собрать установщик и поставить приложение.

### 1) Что нужно заранее

- macOS (Intel или Apple Silicon)
- Интернет
- Xcode Command Line Tools:

```bash
xcode-select --install
```

- Python 3.14 (проверь командой):

```bash
python3.14 --version
```

Если команды нет — установи Python 3.14 (например, через официальный инсталлер с [python.org](https://www.python.org/downloads/)).

### 2) Скачать и распаковать архив проекта

Скачай исходники проекта (zip/tar.gz), распакуй в удобную папку, затем открой Terminal в этой папке.

Пример:

```bash
cd "/путь/к/распакованному/wow-parser"
```

### 3) Собрать macOS installer (.dmg)

```bash
chmod +x build_macos_installer.sh
./build_macos_installer.sh
```

По умолчанию собирается под текущую архитектуру (`native`).

Если нужно вручную:

```bash
TARGET_ARCH=arm64 ./build_macos_installer.sh
TARGET_ARCH=x86_64 ./build_macos_installer.sh
```

Готовые файлы будут в `dist/`:

- `Wow Parser.app`
- `wow-parser-macos-installer-<arch>-v<version>.dmg`

### 4) Установить приложение

- Открой `.dmg`
- Перетащи `Wow Parser.app` в `Applications`
- Запусти приложение из `Applications`

Если macOS ругается на неизвестного разработчика:

```bash
xattr -dr com.apple.quarantine "/Applications/Wow Parser.app"
open -a "Wow Parser"
```

---

## Альтернатива без .dmg (portable архив)

Если хочешь отдать человеку один архив и установку "почти в один клик":

### На машине разработчика

```bash
chmod +x create_portable_archive.sh
./create_portable_archive.sh
```

Результат:

- `dist/wow-parser-portable-v<version>.tar.gz`

### На целевой машине

Вариант через Finder:

1. Распаковать архив
2. Открыть папку `wow-parser-portable`
3. Двойной клик по `install.command`

Вариант через Terminal:

```bash
tar -xzf wow-parser-portable-v<version>.tar.gz
cd wow-parser-portable
chmod +x run.sh build_and_install_app.sh install.command
./build_and_install_app.sh
```

После установки запуск:

```bash
open -a "Wow Parser"
```

---

## Сборка Windows installer

Собирать нужно на Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_installer.ps1
```

Результат:

- `dist\wow-parser-windows-installer-v<version>.exe`

> Нужен Inno Setup 6.

---

## Локальный запуск без установки (для разработки)

```bash
python3.14 app_ui.py
```

Откроется локальный UI в браузере.

---

## Сборка в 1 бинарник

```bash
chmod +x build_one_binary.sh
./build_one_binary.sh
```

Результат:

- `dist/wow-parser-app`

Запуск:

```bash
./dist/wow-parser-app
```

---

## Что вводить в UI

- `VK Token` — токен VK (если нужен VK парсер)
- `Pinterest token/cookie` — cookie-строка Pinterest для приватной статистики
- `URLs` — ссылки по одной в строке
- `wowData` — если используешь режим WOW API

---

## Что генерируется

- `report.html` — главная страница отчета
- `report.json` — общий JSON по всем платформам
- `vk_index.html`, `tiktok_index.html`, `youtube_index.html`, `dzen_index.html`, `pinterest_index.html`
- `*_result.json` — технические JSON по платформам

---

## CI/CD

Есть workflow: `.github/workflows/build-installers.yml`

- `workflow_dispatch` и теги `v*`
- сборка macOS (`arm64`, `x86_64`) и Windows installer
- артефакты доступны в GitHub Actions
