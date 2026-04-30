# WOW Parser Unified App

Единое приложение для парсинга и отчетов по платформам:

- VK
- TikTok
- YouTube
- Dzen
- Pinterest

Пайплайн:

1. (опционально) загрузка ссылок из WOW API (`src/core/wow_urls_fetcher.py`);
2. нормализация и разбиение ссылок (`src/core/urls_splitter.py`);
3. параллельный парсинг соцсетей;
4. генерация отчетов (`report.html`, `report.json` + отдельные страницы по платформам).

## Установка "на самом простом языке"

Ниже инструкция для человека, который вообще не связан с IT.

### Что нужно

- MacBook/iMac на macOS
- Интернет
- 20-40 минут времени (первый запуск может быть долгим)

### Шаг 1. Скачай проект

1. Скачай архив проекта `wow-parser` (кнопка Download ZIP в GitHub).
2. Открой папку `Загрузки`.
3. Дважды кликни по архиву, чтобы распаковать.
4. Появится папка `wow-parser`.

### Шаг 2. Открой Terminal

1. Нажми `Cmd + Space`.
2. Напиши `Terminal`.
3. Нажми `Enter`.

Откроется окно с текстом.

### Шаг 3. Перейди в папку проекта

Скопируй и вставь команду:

```bash
cd ~/Downloads/wow-parser
```

Если папка лежит не в `Downloads`, просто перетащи папку `wow-parser` в окно Terminal — путь подставится сам.

### Шаг 4. Запусти установку приложения

Вставь по очереди 2 команды:

```bash
chmod +x build_macos_installer.sh
./build_macos_installer.sh
```

Что будет происходить:
- будут бежать строки текста (это нормально);
- может занять 10-30 минут;
- в конце появится готовый установщик.

### Шаг 5. Установи приложение

1. Открой папку `wow-parser/dist`.
2. Найди файл с названием вроде `wow-parser-macos-installer-... .dmg`.
3. Открой его двойным кликом.
4. Перетащи `Wow Parser.app` в `Applications`.

### Шаг 6. Первый запуск

1. Открой `Applications`.
2. Запусти `Wow Parser`.

Если macOS покажет предупреждение про "неизвестного разработчика", вставь в Terminal:

```bash
xattr -dr com.apple.quarantine "/Applications/Wow Parser.app"
open -a "Wow Parser"
```

После этого приложение запустится.

### Если что-то не получается

- Закрой Terminal и открой заново.
- Еще раз сделай шаги 3-5.
- Проверь интернет.
- Убедись, что свободно хотя бы 5-10 ГБ на диске.

## Структура проекта

- `src/ui/` — веб-интерфейс приложения
- `src/core/` — оркестратор пайплайна, сплиттер ссылок, WOW fetcher
- `src/parsers/` — парсеры по платформам
- `entrypoints/` — легковесные точки входа для запуска и сборки
- `scripts/` — основные shell/installer-скрипты
- корневые `*.sh`/`*.ps1`/`install.command` — совместимые обертки на `scripts/`
- `scripts/windows-installer.iss` — сценарий Inno Setup для Windows installer

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
python3.14 entrypoints/app_ui.py
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
