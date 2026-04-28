#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
from urllib.parse import urlparse

import requests


MONTHS_RU = {
    1: "янв",
    2: "фев",
    3: "мар",
    4: "апр",
    5: "май",
    6: "июн",
    7: "июл",
    8: "авг",
    9: "сен",
    10: "окт",
    11: "ноя",
    12: "дек",
}


BAD_DESCRIPTIONS = [
    "thưởng thức video và nhạc bạn yêu thích",
    "tải nội dung do bạn sáng tạo lên",
    "share your videos with friends",
    "enjoy the videos and music you love",
    "upload original content",
    "смотрите любимые видео",
    "загружайте оригинальный контент",
]


def is_bad_description(value):
    if not value:
        return True

    normalized = html.unescape(value).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)

    return any(bad in normalized for bad in BAD_DESCRIPTIONS)


def clean_html_entity(value):
    if value is None:
        return ""

    value = html.unescape(value).strip()
    value = value.replace("\\n", "\n").replace("\\r", "\r")
    value = re.sub(r"\r\n?", "\n", value)
    return value.strip()


def extract_with_regex(pattern, text, flags=0):
    match = re.search(pattern, text, flags)
    return match.group(1) if match else ""


def extract_json_after_marker(page_html, marker):
    """
    Достает JSON после маркера:
    var ytInitialPlayerResponse = {...};
    или
    ytInitialData = {...};
    """
    start = page_html.find(marker)
    if start == -1:
        return None

    brace_start = page_html.find("{", start)
    if brace_start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(brace_start, len(page_html)):
        char = page_html[i]

        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    raw = page_html[brace_start:i + 1]
                    try:
                        return json.loads(raw)
                    except Exception:
                        return None

    return None


def format_datetime_ru(date_str):
    if not date_str:
        return ""

    patterns = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]

    parsed = None

    for pattern in patterns:
        try:
            parsed = dt.datetime.strptime(date_str, pattern)
            break
        except Exception:
            continue

    if not parsed:
        return date_str

    if parsed.hour == 0 and parsed.minute == 0:
        return "{:02d} {} {}".format(
            parsed.day,
            MONTHS_RU.get(parsed.month, str(parsed.month)),
            parsed.year,
        )

    return "{:02d} {} {} {:02d}:{:02d}".format(
        parsed.day,
        MONTHS_RU.get(parsed.month, str(parsed.month)),
        parsed.year,
        parsed.hour,
        parsed.minute,
    )


def extract_short_id(url):
    try:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        parts = path.split("/")

        if len(parts) >= 2 and parts[0] == "shorts":
            return parts[1]

        if parsed.query:
            match = re.search(r"(?:v=)([^&]+)", parsed.query)
            if match:
                return match.group(1)

    except Exception:
        pass

    return ""


def normalize_youtube_url(url):
    short_id = extract_short_id(url)
    if short_id:
        return f"https://www.youtube.com/shorts/{short_id}"
    return url


def make_headers(referer=None):
    return {
        "Referer": referer or "https://www.youtube.com/shorts",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }


def pick_description(candidates):
    for value in candidates:
        value = clean_html_entity(value)
        if value and not is_bad_description(value):
            return value
    return ""


def parse_json_ld(page_html):
    result = {
        "description": "",
        "date_published_raw": "",
        "owner_name": "",
        "owner_url": "",
        "owner_id": "",
        "views": 0,
    }

    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for raw in scripts:
        try:
            data = json.loads(html.unescape(raw).strip())
        except Exception:
            continue

        objects = data if isinstance(data, list) else [data]

        for obj in objects:
            if not isinstance(obj, dict):
                continue

            if obj.get("@type") not in ("VideoObject", "Movie", "Clip"):
                continue

            if not result["description"]:
                result["description"] = obj.get("description", "") or ""

            if not result["date_published_raw"]:
                result["date_published_raw"] = obj.get("uploadDate", "") or obj.get("datePublished", "") or ""

            author = obj.get("author")
            if isinstance(author, dict):
                if not result["owner_name"]:
                    result["owner_name"] = author.get("name", "") or ""
                if not result["owner_url"]:
                    result["owner_url"] = author.get("url", "") or ""

            interaction = obj.get("interactionStatistic")
            if isinstance(interaction, list):
                for stat in interaction:
                    if not isinstance(stat, dict):
                        continue
                    interaction_type = str(stat.get("interactionType", ""))
                    if "WatchAction" in interaction_type:
                        try:
                            result["views"] = int(stat.get("userInteractionCount") or 0)
                        except Exception:
                            result["views"] = 0
            elif isinstance(interaction, dict):
                try:
                    result["views"] = int(interaction.get("userInteractionCount") or 0)
                except Exception:
                    result["views"] = 0

    return result


def parse_youtube_html(page_html):
    player_response = (
        extract_json_after_marker(page_html, "var ytInitialPlayerResponse")
        or extract_json_after_marker(page_html, "ytInitialPlayerResponse")
        or {}
    )

    json_ld = parse_json_ld(page_html)

    video_details = player_response.get("videoDetails", {}) if isinstance(player_response, dict) else {}
    microformat = (
        player_response
        .get("microformat", {})
        .get("playerMicroformatRenderer", {})
        if isinstance(player_response, dict)
        else {}
    )

    views = 0

    # 1. views из videoDetails
    try:
        views = int(video_details.get("viewCount") or 0)
    except Exception:
        views = 0

    # 2. views из WatchAction
    if not views:
        blocks = re.findall(
            r'(<div[^>]+itemprop=["\']interactionStatistic["\'][^>]*>.*?</div>)',
            page_html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        for block in blocks:
            if re.search(
                r'<meta[^>]+itemprop=["\']interactionType["\'][^>]+content=["\']https://schema\.org/WatchAction["\']',
                block,
                flags=re.IGNORECASE,
            ):
                views_str = extract_with_regex(
                    r'<meta[^>]+itemprop=["\']userInteractionCount["\'][^>]+content=["\'](\d+)["\']',
                    block,
                    flags=re.IGNORECASE,
                )
                if views_str:
                    try:
                        views = int(views_str)
                    except Exception:
                        views = 0
                break

    # 3. views из JSON-LD
    if not views:
        views = json_ld.get("views", 0) or 0

    date_published = (
        microformat.get("publishDate")
        or microformat.get("uploadDate")
        or json_ld.get("date_published_raw")
        or clean_html_entity(
            extract_with_regex(
                r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)["\']',
                page_html,
                flags=re.IGNORECASE,
            )
        )
    )

    owner_name = (
        microformat.get("ownerChannelName")
        or video_details.get("author")
        or json_ld.get("owner_name")
        or clean_html_entity(
            extract_with_regex(
                r'<link[^>]+itemprop=["\']name["\'][^>]+content=["\']([^"\']+)["\']',
                page_html,
                flags=re.IGNORECASE,
            )
        )
    )

    owner_url = (
        microformat.get("ownerProfileUrl")
        or json_ld.get("owner_url")
        or ""
    )

    if owner_url and owner_url.startswith("/"):
        owner_url = "https://www.youtube.com" + owner_url

    owner_id = (
        video_details.get("channelId")
        or microformat.get("externalChannelId")
        or ""
    )

    owner_avatar = ""
    try:
        thumbs = (
            microformat
            .get("ownerProfileUrl")
        )
    except Exception:
        pass

    description_candidates = [
        video_details.get("shortDescription", ""),
        microformat.get("description", {}).get("simpleText", "") if isinstance(microformat.get("description"), dict) else "",
        microformat.get("description", {}).get("runs", [{}])[0].get("text", "") if isinstance(microformat.get("description"), dict) and microformat.get("description", {}).get("runs") else "",
        json_ld.get("description", ""),
        clean_html_entity(
            extract_with_regex(
                r'<meta[^>]+itemprop=["\']description["\'][^>]+content=["\']([^"\']*)["\']',
                page_html,
                flags=re.IGNORECASE,
            )
        ),
        clean_html_entity(
            extract_with_regex(
                r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']*)["\']',
                page_html,
                flags=re.IGNORECASE,
            )
        ),
    ]

    description = pick_description(description_candidates)

    if not description:
        title_value = clean_html_entity(
            extract_with_regex(
                r"<title>(.*?)</title>",
                page_html,
                flags=re.IGNORECASE | re.DOTALL,
            )
        )

        if title_value:
            title_value = re.sub(
                r"\s*-\s*YouTube\s*$",
                "",
                title_value,
                flags=re.IGNORECASE,
            ).strip()

            if not is_bad_description(title_value):
                description = title_value

    return {
        "views": int(views or 0),
        "date_published_raw": date_published,
        "date_published_display": format_datetime_ru(date_published),
        "description": description,
        "owner_id": owner_id,
        "owner_name": owner_name,
        "owner_url": owner_url,
        "owner_avatar": owner_avatar,
    }


def load_urls(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines()]

    return [line for line in lines if line]


def fetch_short_info(session, url, referer=None, timeout=30):
    normalized_url = normalize_youtube_url(url)

    response = session.get(
        normalized_url,
        headers=make_headers(referer=referer),
        timeout=timeout,
    )
    response.raise_for_status()

    parsed = parse_youtube_html(response.text)
    short_id = extract_short_id(normalized_url)

    return {
        "url": normalized_url,
        "short_id": short_id,
        "views": parsed["views"],
        "date_published_raw": parsed["date_published_raw"],
        "date_published_display": parsed["date_published_display"],
        "description": parsed["description"],
        "owner_id": parsed["owner_id"] or parsed["owner_name"] or "unknown",
        "owner_name": parsed["owner_name"] or "Unknown",
        "owner_url": parsed["owner_url"],
        "owner_avatar": parsed["owner_avatar"],
    }


def build_items(urls, pause_sec=0.0, referer=None, verbose=False):
    session = requests.Session()
    items = []

    for index, url in enumerate(urls, start=1):
        if verbose:
            print(f"Fetching {index} / {len(urls)} | {url}", file=sys.stderr)

        try:
            info = fetch_short_info(session, url, referer=referer)
            info["source_index"] = index
            items.append(info)
        except Exception as e:
            items.append({
                "url": url,
                "short_id": extract_short_id(url),
                "views": 0,
                "date_published_raw": "",
                "date_published_display": "",
                "description": f"ERROR: {str(e)}",
                "owner_id": "unknown",
                "owner_name": "Unknown",
                "owner_url": "",
                "owner_avatar": "",
                "source_index": index,
            })

        if pause_sec > 0 and index < len(urls):
            time.sleep(pause_sec)

    return items


def build_owner_summary(items):
    owners = {}

    for item in items:
        owner_id = item.get("owner_id") or item.get("owner_name") or "unknown"

        if owner_id not in owners:
            owners[owner_id] = {
                "owner_id": owner_id,
                "owner_name": item.get("owner_name", ""),
                "owner_url": item.get("owner_url", ""),
                "videos_count": 0,
                "views_sum": 0,
            }

        owners[owner_id]["videos_count"] += 1
        owners[owner_id]["views_sum"] += int(item.get("views") or 0)

    return sorted(
        owners.values(),
        key=lambda x: x["views_sum"],
        reverse=True,
    )


def build_owner_rows(items):
    rows = []

    for owner in build_owner_summary(items):
        avg_views = round(owner["views_sum"] / owner["videos_count"]) if owner["videos_count"] else 0

        rows.append("""
        <tr>
            <td>
                <a href="{owner_url}" target="_blank" rel="noopener noreferrer">
                    <strong>{owner_name}</strong>
                </a>
                <div class="muted">{owner_id}</div>
            </td>
            <td>{videos_count}</td>
            <td>{views_sum}</td>
            <td>{avg_views}</td>
        </tr>
        """.format(
            owner_url=html.escape(owner.get("owner_url") or "", quote=True),
            owner_name=html.escape(owner.get("owner_name") or ""),
            owner_id=html.escape(str(owner.get("owner_id") or "")),
            videos_count=owner["videos_count"],
            views_sum=owner["views_sum"],
            avg_views=avg_views,
        ))

    return "\n".join(rows)


def build_html_table(items):
    rows = []

    for item in items:
        idx = item["source_index"]

        row = """
        <tr class="data-row"
            data-search="{search_attr}"
            data-views="{views}"
            data-manually-hidden="0">
            <td><input type="checkbox" class="row-check"></td>
            <td>{idx}</td>
            <td>{date}</td>
            <td>{views}</td>
            <td>
                <a href="{owner_url}" target="_blank" rel="noopener noreferrer">
                    <strong>{owner_name}</strong>
                </a>
                <div class="muted">{owner_id}</div>
            </td>
            <td><a href="{url}" target="_blank" rel="noopener noreferrer">{url_text}</a></td>
            <td>{short_id}</td>
            <td class="description-cell">{description}</td>
        </tr>
        """.format(
            search_attr=html.escape(
                "{} {} {} {}".format(
                    item.get("description", ""),
                    item.get("owner_name", ""),
                    item.get("short_id", ""),
                    item.get("url", ""),
                ).lower(),
                quote=True,
            ),
            views=int(item["views"] or 0),
            idx=idx,
            date=html.escape(item["date_published_display"]),
            owner_url=html.escape(item.get("owner_url") or "", quote=True),
            owner_name=html.escape(item.get("owner_name") or ""),
            owner_id=html.escape(str(item.get("owner_id") or "")),
            url=html.escape(item["url"], quote=True),
            url_text=html.escape(item["url"]),
            short_id=html.escape(item["short_id"]),
            description=html.escape(item["description"]),
        )

        rows.append(row)

    return "\n".join(rows)


def render_html(items, title="YouTube Shorts"):
    rows_html = build_html_table(items)
    owner_rows_html = build_owner_rows(items)

    total_views = sum(int(item.get("views") or 0) for item in items)
    total_owners = len({str(item.get("owner_id")) for item in items if item.get("owner_id")})

    html_template = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>__TITLE__</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 24px;
            background: #f3f5f8;
            color: #1f2937;
        }

        h1 {
            margin-bottom: 12px;
        }

        h2 {
            margin-top: 28px;
        }

        .toolbar {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            align-items: flex-start;
            margin-bottom: 18px;
            padding: 16px;
            background: #ffffff;
            border: 1px solid #d6dde8;
            border-radius: 12px;
        }

        .toolbar label {
            font-weight: 700;
        }

        .toolbar input[type="text"] {
            min-width: 360px;
            padding: 9px 12px;
            border: 1px solid #bcc7d6;
            border-radius: 8px;
            font-size: 14px;
        }

        .toolbar-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
        }

        .toolbar-actions button {
            padding: 10px 14px;
            border: 1px solid #c7d2e0;
            background: #eef3f8;
            border-radius: 10px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
        }

        .toolbar-actions button:hover {
            background: #e4ebf3;
        }

        .stat-box {
            padding: 10px 14px;
            background: #eef3f8;
            border-radius: 10px;
            border: 1px solid #d4dde8;
            font-size: 14px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: #ffffff;
            margin-bottom: 22px;
        }

        th, td {
            border: 1px solid #d7dee8;
            padding: 10px;
            text-align: left;
            vertical-align: top;
            font-size: 14px;
        }

        th {
            background: #e9eff6;
            position: sticky;
            top: 0;
            z-index: 2;
        }

        tr.hidden-row {
            display: none;
        }

        tr.selected-row td {
            box-shadow: inset 0 0 0 9999px rgba(37, 99, 235, 0.14);
        }

        .description-cell {
            min-width: 360px;
            white-space: pre-wrap;
        }

        .muted {
            color: #667085;
            font-size: 12px;
            margin-top: 3px;
        }

        a {
            color: #1d4ed8;
            text-decoration: none;
            word-break: break-all;
        }

        a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <h1>__TITLE__</h1>

    <div class="toolbar">
        <div>
            <label for="searchFilter">Фильтр:</label><br>
            <input type="text" id="searchFilter" placeholder="Канал, описание, ссылка или Short ID">
        </div>

        <div class="toolbar-actions">
            <button type="button" id="hideSelectedBtn">Скрыть выделенные</button>
            <button type="button" id="showAllHiddenBtn">Показать все скрытые</button>
        </div>

        <div class="stat-box">
            Всего shorts: <strong id="totalCount">__COUNT__</strong>
        </div>

        <div class="stat-box">
            Каналов: <strong>__OWNERS__</strong>
        </div>

        <div class="stat-box">
            Всего просмотров: <strong>__TOTAL_VIEWS__</strong>
        </div>

        <div class="stat-box">
            Видимых строк: <strong id="visibleCount">__COUNT__</strong>
        </div>

        <div class="stat-box">
            Скрыто вручную: <strong id="manuallyHiddenCount">0</strong>
        </div>

        <div class="stat-box">
            Выбрано строк: <strong id="selectedCount">0</strong>
        </div>

        <div class="stat-box">
            Сумма просмотров выбранных: <strong id="selectedViews">0</strong>
        </div>
    </div>

    <h2>Сводка по каналам</h2>

    <table>
        <thead>
            <tr>
                <th>Канал</th>
                <th>Shorts</th>
                <th>Просмотры</th>
                <th>Средние просмотры</th>
            </tr>
        </thead>
        <tbody>
            __OWNER_ROWS__
        </tbody>
    </table>

    <h2>Детализация по Shorts</h2>

    <table>
        <thead>
            <tr>
                <th><input type="checkbox" id="checkAllVisible"></th>
                <th>#</th>
                <th>Дата публикации</th>
                <th>Просмотры</th>
                <th>Канал</th>
                <th>Ссылка</th>
                <th>Short ID</th>
                <th>Описание</th>
            </tr>
        </thead>
        <tbody id="tableBody">
            __ROWS__
        </tbody>
    </table>

    <script>
        const filterInput = document.getElementById('searchFilter');
        const rows = Array.from(document.querySelectorAll('.data-row'));
        const selectedCountEl = document.getElementById('selectedCount');
        const selectedViewsEl = document.getElementById('selectedViews');
        const visibleCountEl = document.getElementById('visibleCount');
        const totalCountEl = document.getElementById('totalCount');
        const manuallyHiddenCountEl = document.getElementById('manuallyHiddenCount');
        const checkAllVisible = document.getElementById('checkAllVisible');
        const hideSelectedBtn = document.getElementById('hideSelectedBtn');
        const showAllHiddenBtn = document.getElementById('showAllHiddenBtn');

        function formatNumber(num) {
            return String(num);
        }

        function isManuallyHidden(row) {
            return row.dataset.manuallyHidden === '1';
        }

        function isTextMatch(row, query) {
            const text = row.dataset.search || '';

            if (!query) return true;

            const parts = query
                .split('±')
                .map(p => p.trim())
                .filter(Boolean);

            if (!parts.length) return true;

            return parts.some(part => text.includes(part));
        }

        function applyVisibility() {
            const query = filterInput.value.trim().toLowerCase();

            rows.forEach(row => {
                const matchesFilter = isTextMatch(row, query);
                const hiddenManual = isManuallyHidden(row);

                if (matchesFilter && !hiddenManual) {
                    row.classList.remove('hidden-row');
                } else {
                    row.classList.add('hidden-row');
                }
            });
        }

        function getVisibleRows() {
            return rows.filter(row => !row.classList.contains('hidden-row') && !isManuallyHidden(row));
        }

        function updateCounters() {
            const visibleRows = getVisibleRows();
            const manuallyHiddenCount = rows.filter(row => isManuallyHidden(row)).length;

            visibleCountEl.textContent = formatNumber(visibleRows.length);
            manuallyHiddenCountEl.textContent = formatNumber(manuallyHiddenCount);
            totalCountEl.textContent = formatNumber(rows.length);
        }

        function updateSelectionSummary() {
            let selectedCount = 0;
            let selectedViews = 0;

            rows.forEach(row => {
                const checkbox = row.querySelector('.row-check');

                if (checkbox.checked) {
                    selectedCount += 1;
                    selectedViews += Number(row.dataset.views || 0);
                    row.classList.add('selected-row');
                } else {
                    row.classList.remove('selected-row');
                }
            });

            selectedCountEl.textContent = formatNumber(selectedCount);
            selectedViewsEl.textContent = formatNumber(selectedViews);
        }

        function refreshAll() {
            applyVisibility();
            updateCounters();
            updateSelectionSummary();
            checkAllVisible.checked = false;
        }

        function toggleAllVisible(checked) {
            rows.forEach(row => {
                if (!row.classList.contains('hidden-row') && !isManuallyHidden(row)) {
                    row.querySelector('.row-check').checked = checked;
                }
            });

            updateSelectionSummary();
        }

        function hideSelectedRows() {
            rows.forEach(row => {
                const checkbox = row.querySelector('.row-check');

                if (checkbox.checked) {
                    row.dataset.manuallyHidden = '1';
                    checkbox.checked = false;
                }
            });

            refreshAll();
        }

        function showAllHiddenRows() {
            rows.forEach(row => {
                row.dataset.manuallyHidden = '0';
            });

            refreshAll();
        }

        rows.forEach(row => {
            row.dataset.manuallyHidden = '0';
            row.querySelector('.row-check').addEventListener('change', updateSelectionSummary);
        });

        filterInput.addEventListener('input', refreshAll);

        checkAllVisible.addEventListener('change', function() {
            toggleAllVisible(this.checked);
        });

        hideSelectedBtn.addEventListener('click', hideSelectedRows);
        showAllHiddenBtn.addEventListener('click', showAllHiddenRows);

        refreshAll();
    </script>
</body>
</html>
"""

    return (
        html_template
        .replace("__TITLE__", html.escape(title))
        .replace("__COUNT__", str(len(items)))
        .replace("__OWNERS__", str(total_owners))
        .replace("__TOTAL_VIEWS__", str(total_views))
        .replace("__OWNER_ROWS__", owner_rows_html)
        .replace("__ROWS__", rows_html)
    )


def main():
    parser = argparse.ArgumentParser(description="Parse YouTube Shorts to index.html, grouped by channel")
    parser.add_argument("--input", default="shorts.txt", help="Файл со списком YouTube Shorts URL")
    parser.add_argument("--output", default="index.html", help="Имя output HTML файла")
    parser.add_argument("--title", default="YouTube Shorts", help="Заголовок страницы")
    parser.add_argument("--pause", type=float, default=0.5, help="Пауза между запросами в секундах")
    parser.add_argument("--referer", default="https://www.youtube.com/shorts", help="Referer header")
    parser.add_argument("--save-json", help="Сохранить распарсенные данные в JSON")
    parser.add_argument("--verbose", action="store_true", help="Печатать прогресс в stderr")

    args = parser.parse_args()

    try:
        urls = load_urls(args.input)

        if not urls:
            raise RuntimeError(f"Входной файл пустой: {args.input}")

        items = build_items(
            urls=urls,
            pause_sec=args.pause,
            referer=args.referer,
            verbose=args.verbose,
        )

        page = render_html(items, title=args.title)

        with open(args.output, "w", encoding="utf-8") as f:
            f.write(page)

        if args.save_json:
            with open(args.save_json, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)

        print(f"HTML saved to {args.output}")

    except Exception as e:
        print("ERROR:", str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
