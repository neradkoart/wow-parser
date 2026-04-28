#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as dt
import html
import json
import re
import shlex
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests


MONTHS_RU = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def clean_text(value):
    if value is None:
        return ""

    value = html.unescape(str(value))
    value = value.replace("\\u002F", "/").replace("\\/", "/")
    value = value.replace("\\n", "\n").replace("\\r", "\r")
    value = re.sub(r"\r\n?", "\n", value)
    value = re.sub(r"[ \t]+", " ", value)

    return value.strip()


def safe_int(value):
    if value is None:
        return 0

    try:
        return int(str(value).replace(",", "").replace(" ", "").strip())
    except Exception:
        return 0


def format_date(value):
    value = clean_text(value)

    if not value:
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
            parsed = dt.datetime.strptime(value, pattern)
            break
        except Exception:
            continue

    if not parsed:
        return value

    return f"{parsed.day:02d} {MONTHS_RU.get(parsed.month, parsed.month)} {parsed.year}"


def normalize_dzen_url(line):
    raw = clean_text(line).strip().strip("'\"")

    match = re.search(r"https?://[^\s'\"<>]+", raw)
    if match:
        raw = match.group(0)

    if not raw:
        return ""

    parsed = urlparse(raw)

    # Оставляем только схему, домен и path. source=channel и прочее не нужно.
    return urlunparse((parsed.scheme or "https", parsed.netloc or "dzen.ru", parsed.path, "", "", ""))


def extract_short_id(url):
    try:
        path = urlparse(url).path
        match = re.search(r"/shorts/([^/?#]+)", path)
        if match:
            return match.group(1)
    except Exception:
        pass

    match = re.search(r"/shorts/([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else ""


def parse_headers_file(path):
    """
    Поддерживает dzen_cookies.txt в формате copy-as-curl без URL:

      -H 'Accept: text/html,...' \
      -H 'User-Agent: Mozilla/5.0 ...' \
      -b 'zencookie=...; yandexuid=...' \

    Возвращает:
      headers: dict с lower-case ключами
      cookie_header: str
    """
    if not path:
        return {}, ""

    raw = Path(path).read_text(encoding="utf-8").strip()

    if not raw:
        return {}, ""

    normalized = raw.replace("\\\r\n", " ").replace("\\\n", " ")

    headers = {}
    cookie_header = ""

    try:
        tokens = shlex.split(normalized)
    except Exception:
        tokens = []

    if tokens:
        i = 0

        while i < len(tokens):
            token = tokens[i]

            if token in ("-H", "--header") and i + 1 < len(tokens):
                header_line = tokens[i + 1]

                if ":" in header_line:
                    key, value = header_line.split(":", 1)
                    headers[key.strip().lower()] = value.strip()

                i += 2
                continue

            if token in ("-b", "--cookie") and i + 1 < len(tokens):
                cookie_header = tokens[i + 1].strip()
                i += 2
                continue

            i += 1

    else:
        for match in re.finditer(r"-H\s+(['\"])(.*?)\1", normalized, flags=re.S):
            header_line = match.group(2)

            if ":" in header_line:
                key, value = header_line.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        match = re.search(r"-b\s+(['\"])(.*?)\1", normalized, flags=re.S)
        if match:
            cookie_header = match.group(2).strip()

    return headers, cookie_header


def make_headers(url, extra_headers=None, cookie_header=""):
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "referer": url,
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    }

    skip = {
        "host",
        "content-length",
        "connection",
        "accept-encoding",
    }

    for key, value in (extra_headers or {}).items():
        lk = key.lower().strip()
        if lk not in skip:
            headers[lk] = value

    if cookie_header:
        headers["cookie"] = cookie_header

    return headers


def extract_meta(page_html, name_or_property):
    patterns = [
        rf'<meta[^>]+name=["\']{re.escape(name_or_property)}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+property=["\']{re.escape(name_or_property)}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']{re.escape(name_or_property)}["\']',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']{re.escape(name_or_property)}["\']',
    ]

    for pattern in patterns:
        match = re.search(pattern, page_html, flags=re.I | re.S)
        if match:
            return clean_text(match.group(1))

    return ""


def extract_title_tag(page_html):
    match = re.search(r"<title>(.*?)</title>", page_html, flags=re.I | re.S)
    return clean_text(match.group(1)) if match else ""


def parse_json_ld(page_html):
    """
    В примере есть script id="video-microdata" type="application/ld+json".
    Там лежат description, uploadDate, name, interactionStatistic.
    """
    result = {}

    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.I | re.S,
    )

    for raw in scripts:
        raw = html.unescape(raw.strip())

        try:
            data = json.loads(raw)
        except Exception:
            continue

        objects = data if isinstance(data, list) else [data]

        for obj in objects:
            if not isinstance(obj, dict):
                continue

            if obj.get("@type") != "VideoObject":
                continue

            result["description"] = clean_text(obj.get("description"))
            result["title"] = clean_text(obj.get("name"))
            result["date_published_raw"] = clean_text(obj.get("uploadDate"))
            result["embed_url"] = clean_text(obj.get("embedUrl"))
            result["thumbnail"] = clean_text(obj.get("thumbnailUrl") or obj.get("thumbnail", {}).get("contentUrl") if isinstance(obj.get("thumbnail"), dict) else "")

            stats = obj.get("interactionStatistic") or []

            if isinstance(stats, list):
                for stat in stats:
                    if not isinstance(stat, dict):
                        continue

                    interaction_type = stat.get("interactionType")

                    if isinstance(interaction_type, dict):
                        interaction_type = interaction_type.get("@type", "")

                    count = safe_int(stat.get("userInteractionCount"))

                    if interaction_type == "WatchAction":
                        result["views"] = count
                    elif interaction_type == "LikeAction":
                        result["likes"] = count
                    elif interaction_type == "CommentAction":
                        result["comments"] = count

            return result

    return result


def extract_balanced_json_after_marker(text, marker):
    start = text.find(marker)

    if start == -1:
        return None

    brace_start = text.find("{", start)

    if brace_start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(brace_start, len(text)):
        char = text[i]

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
                    raw = text[brace_start:i + 1]
                    try:
                        return json.loads(raw)
                    except Exception:
                        return None

    return None


def recursive_find_publication(obj, short_id=""):
    """
    Fallback по большим JS объектам.
    Ищет словарь, где рядом есть publication_oid / title / views.
    """
    if isinstance(obj, dict):
        obj_text_id = clean_text(obj.get("publication_oid") or obj.get("publicationOid") or obj.get("id") or obj.get("publicationId"))

        if short_id and obj_text_id == short_id:
            return obj

        keys = set(obj.keys())
        if ("views" in keys or "viewsCount" in keys) and ("title" in keys or "name" in keys):
            return obj

        for value in obj.values():
            found = recursive_find_publication(value, short_id=short_id)
            if found:
                return found

    elif isinstance(obj, list):
        for value in obj:
            found = recursive_find_publication(value, short_id=short_id)
            if found:
                return found

    return None


def parse_author_and_title_from_og(og_title):
    """
    Пример:
    man_health | описание | Дзен
    """
    og_title = clean_text(og_title)

    if not og_title:
        return "", ""

    parts = [p.strip() for p in og_title.split("|")]

    if len(parts) >= 2:
        author = parts[0]
        title = parts[1]
        return author, title

    return "", og_title


def clean_description(value, owner_name=""):
    value = clean_text(value)

    if not value:
        return ""

    # JSON-LD description часто начинается с:
    # Видео автора «man_health» в Дзене 🎦:
    value = re.sub(r"^Видео автора «[^»]+» в Дзене\s*🎦:\s*", "", value).strip()
    value = re.sub(r"^Ролики автора «[^»]+» в Дзене\s*🎦:\s*", "", value).strip()

    if owner_name:
        value = value.replace(f"Видео автора «{owner_name}» в Дзене 🎦:", "").strip()
        value = value.replace(f"Ролики автора «{owner_name}» в Дзене 🎦:", "").strip()

    return value


def parse_dzen_html(page_html, source_url):
    source_url = normalize_dzen_url(source_url)
    short_id = extract_short_id(source_url)

    json_ld = parse_json_ld(page_html)

    og_title = extract_meta(page_html, "og:title") or extract_title_tag(page_html)
    owner_from_title, title_from_og = parse_author_and_title_from_og(og_title)

    title = (
        json_ld.get("title")
        or title_from_og
        or extract_meta(page_html, "twitter:title")
        or extract_title_tag(page_html)
    )

    owner_name = owner_from_title

    description = (
        json_ld.get("description")
        or extract_meta(page_html, "description")
        or extract_meta(page_html, "og:description")
        or title
    )

    description = clean_description(description, owner_name=owner_name)

    # Если description оказался укороченным из meta, а title полный — берем title.
    if title and len(title) > len(description):
        description = clean_description(title, owner_name=owner_name)

    date_raw = (
        json_ld.get("date_published_raw")
        or extract_meta(page_html, "ya:ovs:upload_date")
    )

    views = (
        safe_int(json_ld.get("views"))
        or safe_int(extract_meta(page_html, "ya:ovs:views_total"))
    )

    likes = safe_int(json_ld.get("likes"))
    comments = safe_int(json_ld.get("comments"))
    duration = safe_int(extract_meta(page_html, "video:duration"))
    thumbnail = json_ld.get("thumbnail") or extract_meta(page_html, "og:image") or extract_meta(page_html, "twitter:image")
    canonical = ""

    match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']', page_html, flags=re.I)
    if match:
        canonical = clean_text(match.group(1))

    # Fallback: embedded JS params иногда содержат views/title/author.
    if not views:
        views_match = re.search(r'"views"\s*:\s*(\d+)', page_html)
        if views_match:
            views = safe_int(views_match.group(1))

    if not owner_name:
        # Ищем рядом "title": "man_health". В большом объекте бывает несколько title.
        # Берем первый похожий на короткое имя автора.
        title_candidates = re.findall(r'"title"\s*:\s*"([^"]{1,80})"', page_html)
        for candidate in title_candidates:
            candidate = clean_text(candidate)
            if candidate and not any(x in candidate.lower() for x in ["дзен", "в пенке", "видео", "ролики"]):
                owner_name = candidate
                break

    if not owner_name:
        owner_name = "Unknown"

    return {
        "url": canonical or source_url,
        "short_id": short_id,
        "owner_id": owner_name,
        "owner_name": owner_name,
        "owner_url": "",
        "owner_avatar": "",
        "views": views,
        "likes": likes,
        "comments": comments,
        "date_published_raw": date_raw,
        "date_published_display": format_date(date_raw),
        "duration": duration,
        "thumbnail": thumbnail,
        "description": description,
        "title": title,
        "parse_status": "ok" if views or title or description else "not_found",
    }


def load_urls(path):
    rows = Path(path).read_text(encoding="utf-8").splitlines()
    urls = []
    seen = set()

    for row in rows:
        url = normalize_dzen_url(row)

        if not url or url in seen:
            continue

        seen.add(url)
        urls.append(url)

    return urls


def fetch_items(urls, headers, cookie_header, pause, debug_html_dir, verbose):
    session = requests.Session()
    items = []

    # Прогрев сессии: первый запрос может уйти в passport/sso,
    # но после него Яндекс часто выставляет нужные cookies в requests.Session.
    # Этот ответ НЕ попадает в отчет.
    if urls:
        warmup_url = urls[0]
        try:
            if verbose:
                log(f"[WARMUP] {warmup_url}")

            warmup_response = session.get(
                warmup_url,
                headers=make_headers(warmup_url, extra_headers=headers, cookie_header=cookie_header),
                timeout=40,
                allow_redirects=True,
            )

            if verbose:
                log(f"[WARMUP] status={warmup_response.status_code} final={warmup_response.url}")

            # Если прогрев ушел в SSO, делаем еще один тихий повтор уже с обновленной session.
            if "passport.yandex.ru" in (warmup_response.url or "") or "sso.passport.yandex.ru" in (warmup_response.url or ""):
                time.sleep(1)
                warmup_response_2 = session.get(
                    warmup_url,
                    headers=make_headers(warmup_url, extra_headers=headers, cookie_header=cookie_header),
                    timeout=40,
                    allow_redirects=True,
                )

                if verbose:
                    log(f"[WARMUP-RETRY] status={warmup_response_2.status_code} final={warmup_response_2.url}")

        except Exception as e:
            if verbose:
                log(f"[WARMUP ERROR] {e}")

    for index, url in enumerate(urls, start=1):
        if verbose:
            log(f"Fetching {index} / {len(urls)} | {url}")

        try:
            response = session.get(
                url,
                headers=make_headers(url, extra_headers=headers, cookie_header=cookie_header),
                timeout=40,
                allow_redirects=True,
            )

            page_html = response.text
            response_url = response.url or url

            if "passport.yandex.ru" in response_url or "sso.passport.yandex.ru" in response_url:
                # Не пишем SSO URL в отчет. Пробуем еще раз исходный URL с уже прогретой session.
                if verbose:
                    log(f"[PASSPORT-REDIRECT] retry original url: {url}")

                time.sleep(1)
                response = session.get(
                    url,
                    headers=make_headers(url, extra_headers=headers, cookie_header=cookie_header),
                    timeout=40,
                    allow_redirects=True,
                )

                page_html = response.text
                response_url = response.url or url

            if "passport.yandex.ru" in response_url or "sso.passport.yandex.ru" in response_url:
                final_url = url
            else:
                final_url = normalize_dzen_url(response_url)

            if debug_html_dir and (response.status_code >= 400 or not page_html):
                Path(debug_html_dir).mkdir(parents=True, exist_ok=True)
                Path(debug_html_dir, f"{index}_{extract_short_id(final_url) or 'unknown'}.html").write_text(page_html, encoding="utf-8")

            item = parse_dzen_html(page_html, final_url)
            item["source_index"] = index
            item["http_status"] = response.status_code
            items.append(item)

            if verbose:
                log(f"[OK] {item['owner_name']} | views={item['views']} | {item['date_published_display']}")

        except Exception as e:
            short_id = extract_short_id(url)

            if verbose:
                log(f"[ERROR] {url}: {e}")

            items.append({
                "url": url,
                "short_id": short_id,
                "owner_id": "error",
                "owner_name": "ERROR",
                "owner_url": "",
                "owner_avatar": "",
                "views": 0,
                "likes": 0,
                "comments": 0,
                "date_published_raw": "",
                "date_published_display": "",
                "duration": 0,
                "thumbnail": "",
                "description": f"ERROR: {e}",
                "title": "",
                "parse_status": "error",
                "source_index": index,
                "http_status": 0,
            })

        if pause > 0 and index < len(urls):
            time.sleep(pause)

    return items


def build_owner_summary(items):
    owners = {}

    for item in items:
        key = item.get("owner_id") or item.get("owner_name") or "unknown"

        if key not in owners:
            owners[key] = {
                "owner_id": item.get("owner_id", ""),
                "owner_name": item.get("owner_name", ""),
                "owner_url": item.get("owner_url", ""),
                "owner_avatar": item.get("owner_avatar", ""),
                "videos_count": 0,
                "views_sum": 0,
                "likes_sum": 0,
                "comments_sum": 0,
            }

        owners[key]["videos_count"] += 1
        owners[key]["views_sum"] += safe_int(item.get("views"))
        owners[key]["likes_sum"] += safe_int(item.get("likes"))
        owners[key]["comments_sum"] += safe_int(item.get("comments"))

    return sorted(owners.values(), key=lambda x: x["views_sum"], reverse=True)


def build_owner_rows(items):
    rows = []

    for owner in build_owner_summary(items):
        avg_views = round(owner["views_sum"] / owner["videos_count"]) if owner["videos_count"] else 0

        rows.append(f"""
        <tr>
            <td>
                <strong>{html.escape(owner.get("owner_name") or "")}</strong>
                <div class="muted">ID {html.escape(str(owner.get("owner_id") or ""))}</div>
            </td>
            <td>{owner["videos_count"]}</td>
            <td>{owner["views_sum"]}</td>
            <td>{avg_views}</td>
            <td>{owner["likes_sum"]}</td>
            <td>{owner["comments_sum"]}</td>
        </tr>
        """)

    return "\n".join(rows)


def build_video_rows(items):
    rows = []

    for item in items:
        search = html.escape(
            f'{item.get("description","")} {item.get("owner_name","")} {item.get("short_id","")} {item.get("url","")}'.lower(),
            quote=True,
        )

        thumb = ""
        if item.get("thumbnail"):
            thumb = f'<img class="thumb" src="{html.escape(item.get("thumbnail"), quote=True)}">'

        rows.append(f"""
        <tr class="data-row" data-search="{search}" data-views="{safe_int(item.get("views"))}" data-manually-hidden="0">
            <td><input type="checkbox" class="row-check"></td>
            <td>{item.get("source_index", "")}</td>
            <td>{html.escape(item.get("date_published_display") or "")}</td>
            <td>{safe_int(item.get("views"))}</td>
            <td>{html.escape(item.get("owner_name") or "")}</td>
            <td><a href="{html.escape(item.get("url") or "", quote=True)}" target="_blank">{html.escape(item.get("url") or "")}</a></td>
            <td>{html.escape(item.get("short_id") or "")}</td>
            <td>{safe_int(item.get("likes"))}</td>
            <td>{safe_int(item.get("comments"))}</td>
            <td>{safe_int(item.get("duration"))}</td>
            <td>{thumb}</td>
            <td class="description-cell">{html.escape(item.get("description") or "")}</td>
            <td>{html.escape(item.get("parse_status") or "")}</td>
        </tr>
        """)

    return "\n".join(rows)


def render_html(items, title):
    total_views = sum(safe_int(item.get("views")) for item in items)
    total_owners = len({item.get("owner_id") or item.get("owner_name") for item in items})

    owner_rows = build_owner_rows(items)
    video_rows = build_video_rows(items)

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; background: #f3f5f8; color: #1f2937; }}
.toolbar {{ display:flex; flex-wrap:wrap; gap:12px; align-items:flex-start; margin-bottom:18px; padding:16px; background:#fff; border:1px solid #d6dde8; border-radius:12px; }}
.toolbar input[type="text"] {{ min-width:360px; padding:9px 12px; border:1px solid #bcc7d6; border-radius:8px; }}
.toolbar button {{ padding:10px 14px; border:1px solid #c7d2e0; background:#eef3f8; border-radius:10px; cursor:pointer; font-weight:600; }}
.stat-box {{ padding:10px 14px; background:#eef3f8; border-radius:10px; border:1px solid #d4dde8; }}
table {{ width:100%; border-collapse:collapse; background:#fff; margin-bottom:22px; }}
th, td {{ border:1px solid #d7dee8; padding:10px; text-align:left; vertical-align:top; font-size:14px; }}
th {{ background:#e9eff6; position:sticky; top:0; z-index:2; }}
tr.hidden-row {{ display:none; }}
tr.selected-row td {{ box-shadow: inset 0 0 0 9999px rgba(37,99,235,.14); }}
.description-cell {{ min-width:420px; white-space:pre-wrap; }}
.muted {{ color:#667085; font-size:12px; margin-top:3px; }}
.thumb {{ width:120px; border-radius:8px; }}
a {{ color:#1d4ed8; text-decoration:none; word-break:break-all; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>

<div class="toolbar">
    <div>
        <label for="searchFilter"><b>Фильтр:</b></label><br>
        <input type="text" id="searchFilter" placeholder="Автор, описание, ссылка или Short ID">
    </div>
    <div>
        <button type="button" id="hideSelectedBtn">Скрыть выделенные</button>
        <button type="button" id="showAllHiddenBtn">Показать все скрытые</button>
    </div>
    <div class="stat-box">Всего роликов: <strong id="totalCount">{len(items)}</strong></div>
    <div class="stat-box">Авторов: <strong>{total_owners}</strong></div>
    <div class="stat-box">Всего просмотров: <strong>{total_views}</strong></div>
    <div class="stat-box">Видимых строк: <strong id="visibleCount">{len(items)}</strong></div>
    <div class="stat-box">Скрыто вручную: <strong id="manuallyHiddenCount">0</strong></div>
    <div class="stat-box">Выбрано строк: <strong id="selectedCount">0</strong></div>
    <div class="stat-box">Сумма просмотров выбранных: <strong id="selectedViews">0</strong></div>
</div>

<h2>Сводка по авторам</h2>
<table>
<thead>
<tr>
<th>Автор</th><th>Ролики</th><th>Просмотры</th><th>Средние просмотры</th><th>Лайки</th><th>Комментарии</th>
</tr>
</thead>
<tbody>{owner_rows}</tbody>
</table>

<h2>Детализация по роликам</h2>
<table>
<thead>
<tr>
<th><input type="checkbox" id="checkAllVisible"></th>
<th>#</th><th>Дата публикации</th><th>Просмотры</th><th>Автор</th><th>Ссылка</th><th>Short ID</th><th>Лайки</th><th>Комментарии</th><th>Длительность</th><th>Превью</th><th>Описание</th><th>Статус</th>
</tr>
</thead>
<tbody>{video_rows}</tbody>
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

function formatNumber(num) {{ return String(num); }}
function isManuallyHidden(row) {{ return row.dataset.manuallyHidden === '1'; }}
function isTextMatch(row, query) {{
    const text = row.dataset.search || '';
    if (!query) return true;
    const parts = query.split('±').map(p => p.trim()).filter(Boolean);
    if (!parts.length) return true;
    return parts.some(part => text.includes(part));
}}
function applyVisibility() {{
    const query = filterInput.value.trim().toLowerCase();
    rows.forEach(row => {{
        const visible = isTextMatch(row, query) && !isManuallyHidden(row);
        row.classList.toggle('hidden-row', !visible);
    }});
}}
function getVisibleRows() {{
    return rows.filter(row => !row.classList.contains('hidden-row') && !isManuallyHidden(row));
}}
function updateCounters() {{
    visibleCountEl.textContent = formatNumber(getVisibleRows().length);
    manuallyHiddenCountEl.textContent = formatNumber(rows.filter(row => isManuallyHidden(row)).length);
    totalCountEl.textContent = formatNumber(rows.length);
}}
function updateSelectionSummary() {{
    let selectedCount = 0;
    let selectedViews = 0;
    rows.forEach(row => {{
        const checkbox = row.querySelector('.row-check');
        if (checkbox.checked) {{
            selectedCount++;
            selectedViews += Number(row.dataset.views || 0);
            row.classList.add('selected-row');
        }} else {{
            row.classList.remove('selected-row');
        }}
    }});
    selectedCountEl.textContent = formatNumber(selectedCount);
    selectedViewsEl.textContent = formatNumber(selectedViews);
}}
function refreshAll() {{
    applyVisibility();
    updateCounters();
    updateSelectionSummary();
    checkAllVisible.checked = false;
}}
rows.forEach(row => {{
    row.dataset.manuallyHidden = '0';
    row.querySelector('.row-check').addEventListener('change', updateSelectionSummary);
}});
filterInput.addEventListener('input', refreshAll);
checkAllVisible.addEventListener('change', function() {{
    rows.forEach(row => {{
        if (!row.classList.contains('hidden-row') && !isManuallyHidden(row)) {{
            row.querySelector('.row-check').checked = this.checked;
        }}
    }});
    updateSelectionSummary();
}});
document.getElementById('hideSelectedBtn').addEventListener('click', () => {{
    rows.forEach(row => {{
        const cb = row.querySelector('.row-check');
        if (cb.checked) {{
            row.dataset.manuallyHidden = '1';
            cb.checked = false;
        }}
    }});
    refreshAll();
}});
document.getElementById('showAllHiddenBtn').addEventListener('click', () => {{
    rows.forEach(row => row.dataset.manuallyHidden = '0');
    refreshAll();
}});
refreshAll();
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Dzen shorts parser grouped by author")
    parser.add_argument("--input", default="dzen.txt", help="Файл со ссылками на dzen.ru/shorts/...")
    parser.add_argument("--output", default="index.html", help="HTML отчет")
    parser.add_argument("--title", default="Dzen Shorts", help="Заголовок отчета")
    parser.add_argument("--cookies-file", default="dzen_cookies.txt", help="Файл с copy-as-curl headers/cookies")
    parser.add_argument("--save-json", default="", help="Сохранить JSON")
    parser.add_argument("--pause", type=float, default=0.3, help="Пауза между запросами")
    parser.add_argument("--debug-html-dir", default="", help="Сохранять проблемный HTML")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    urls = load_urls(args.input)

    if not urls:
        raise RuntimeError(f"Файл пустой: {args.input}")

    headers, cookie_header = parse_headers_file(args.cookies_file)

    if args.verbose:
        log(f"[HEADERS] loaded: {len(headers)}")
        log("[COOKIES] loaded" if cookie_header else "[COOKIES] empty")

    items = fetch_items(
        urls=urls,
        headers=headers,
        cookie_header=cookie_header,
        pause=args.pause,
        debug_html_dir=args.debug_html_dir,
        verbose=args.verbose,
    )

    Path(args.output).write_text(render_html(items, args.title), encoding="utf-8")

    if args.save_json:
        Path(args.save_json).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"HTML saved to {args.output}")


if __name__ == "__main__":
    main()
