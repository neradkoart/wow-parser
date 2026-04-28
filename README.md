# WOW Parser Unified App

Проект собран в единое приложение с общим пайплайном:

1. (опционально) загрузка ссылок из WOW API (`wow_urls_fetcher.py`);
2. нормализация и разбиение ссылок (`urls_splitter.py`);
3. парсинг VK / TikTok / YouTube / Dzen;
4. генерация единого отчета (`report.html`) и единого JSON (`report.json`).

## Запуск как единое приложение (CLI)

Используйте Python 3.14 (в этом окружении `python3` указывает на Python 2.7):

```bash
python3.14 unified_app.py --open-report
```

Если нужно сначала тянуть ссылки из WOW API:

```bash
python3.14 unified_app.py --fetch-wow --open-report
```

Флаги отключения платформ:

- `--skip-vk`
- `--skip-tiktok`
- `--skip-youtube`
- `--skip-dzen`

## Что генерируется

- `report.json` — общий формат данных по всем платформам;
- `report.html` — единый интерактивный UI-отчет;
- технические промежуточные файлы (`*_result.json`, `*_index.html`).

## Сборка в 1 бинарник

```bash
chmod +x build_one_binary.sh
./build_one_binary.sh
```

Скрипт сам создает виртуальное окружение `.venv-build`, поэтому не упирается в ошибку `externally-managed-environment` (PEP 668 на Homebrew Python).
Бинарник собирается с UI (`app_ui.py`): в окне можно вставить `VK token`, `urls` или `wowData` и запустить пайплайн кнопкой.

Результат:

- `dist/wow-parser-app`

Запуск бинарника:

```bash
./dist/wow-parser-app
```

## Установщик macOS (.app + .dmg)

```bash
chmod +x build_macos_installer.sh
./build_macos_installer.sh
```

Результаты:

- `dist/Wow Parser.app`
- `dist/wow-parser-macos-installer-v<version>.dmg`

Примечание: для “доверенного” распространения нужен `codesign` + notarization (Apple).

## Установщик Windows (.exe installer)

Собирать нужно на Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_installer.ps1
```

Требуется Inno Setup 6 (установщик берется из `windows-installer.iss`).

Результат:

- `dist\wow-parser-windows-installer-v<version>.exe`

Версия берется из файла `VERSION`.

## Автосборка через GitHub Actions

Добавлен workflow `.github/workflows/build-installers.yml`:

- триггеры: `workflow_dispatch` и теги вида `v*`;
- собирает:
  - macOS: `.app` + `.dmg`
  - Windows: `.exe installer`
- публикует артефакты в Actions.
