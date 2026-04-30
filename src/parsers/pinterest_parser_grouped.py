#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

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
    text = html.unescape(str(value))
    text = text.replace("\\u002F", "/").replace("\\/", "/")
    text = text.replace("\\n", "\n").replace("\\r", "\r")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


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
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
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


def normalize_pin_url(line):
    raw = clean_text(line).strip().strip("'\"")
    m = re.search(r"https?://[^\s'\"<>]+", raw)
    if m:
        raw = m.group(0)
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        pin_match = re.search(r"/pin/(\d+)", parsed.path or "")
        if pin_match:
            return f"https://ru.pinterest.com/pin/{pin_match.group(1)}/"
    except Exception:
        pass
    return raw


def extract_pin_id(url):
    m = re.search(r"/pin/(\d+)", clean_text(url))
    return m.group(1) if m else ""


def is_pin_short_url(url):
    try:
        return urlparse(clean_text(url)).netloc.lower() in ("pin.it", "www.pin.it")
    except Exception:
        return False


def load_urls(path):
    rows = Path(path).read_text(encoding="utf-8").splitlines()
    seen = set()
    urls = []
    for row in rows:
        url = normalize_pin_url(row)
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def resolve_short_url_requests(session, url, cookie_header):
    resolved = normalize_pin_url(url)
    if not is_pin_short_url(resolved):
        return resolved
    return resolve_pinterest_redirect_chain(session, resolved, cookie_header)


def resolve_short_url_playwright(url, cookie_header, headless=True):
    from playwright.sync_api import sync_playwright

    resolved = normalize_pin_url(url)
    if not is_pin_short_url(resolved):
        return resolved

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=headless)
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        locale="ru-RU",
    )
    if cookie_header:
        cookies = []
        for part in cookie_header.split(";"):
            if "=" not in part:
                continue
            name, value = part.strip().split("=", 1)
            if not name:
                continue
            cookies.append(
                {
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".pinterest.com",
                    "path": "/",
                    "secure": True,
                    "httpOnly": False,
                    "sameSite": "Lax",
                }
            )
        if cookies:
            context.add_cookies(cookies)

    page = context.new_page()
    try:
        page.goto(resolved, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        return normalize_pin_url(page.url or resolved)
    finally:
        page.close()
        context.close()
        browser.close()
        pw.stop()


def make_headers(url, cookie_header=""):
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "referer": "https://ru.pinterest.com/",
        "upgrade-insecure-requests": "1",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    }
    if cookie_header:
        headers["cookie"] = cookie_header.strip()
    return headers


def extract_html_redirect_href(text):
    if not text:
        return ""
    m = re.search(r'<a[^>]+href=["\']([^"\']+)["\']', text, flags=re.I)
    if m:
        return clean_text(m.group(1))
    m = re.search(r"target URL:\s*(https?://[^\s<]+)", text, flags=re.I)
    if m:
        return clean_text(m.group(1))
    return ""


def resolve_pinterest_redirect_chain(session, url, cookie_header, max_hops=6):
    current = clean_text(url)
    for _ in range(max_hops):
        response = session.get(
            current,
            headers=make_headers(current, cookie_header),
            timeout=45,
            allow_redirects=True,
        )
        response.raise_for_status()
        final_url = clean_text(response.url or current)
        normalized_final = normalize_pin_url(final_url)
        if extract_pin_id(normalized_final):
            return normalized_final

        html_target = extract_html_redirect_href(response.text or "")
        if not html_target:
            return normalized_final

        current = html_target
    return normalize_pin_url(current)


def extract_balanced_json_after_marker(text, marker):
    start = text.find(marker)
    if start == -1:
        return None
    brace_start = text.find("{", start + len(marker))
    if brace_start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(brace_start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    raw = text[brace_start:i + 1]
                    try:
                        return json.loads(raw)
                    except Exception:
                        return None
    return None


def parse_pin_from_state(state, pin_id):
    if not isinstance(state, dict):
        return {}
    pins = state.get("pins") or {}
    if isinstance(pins, dict):
        if pin_id and pin_id in pins and isinstance(pins[pin_id], dict):
            return pins[pin_id]
        for value in pins.values():
            if isinstance(value, dict) and str(value.get("id", "")) == pin_id:
                return value

    resources = state.get("resources") or {}
    if isinstance(resources, dict):
        pin_resource = resources.get("PinResource") or {}
        if isinstance(pin_resource, dict):
            for entry in pin_resource.values():
                if not isinstance(entry, dict):
                    continue
                data = entry.get("data")
                if isinstance(data, dict):
                    if pin_id and str(data.get("id", "")) == pin_id:
                        return data
                    if not pin_id and data.get("type") == "pin":
                        return data
    return {}


def parse_state(html_text):
    marker = '"initialReduxState":'
    return extract_balanced_json_after_marker(html_text, marker)


def parse_pin(page_html, source_url):
    pin_id = extract_pin_id(source_url)
    state = parse_state(page_html)
    if not state:
        raise RuntimeError("initialReduxState не найден в HTML (проверь cookie Pinterest)")

    pin = parse_pin_from_state(state, pin_id)
    if not pin:
        raise RuntimeError(f"Данные pin не найдены для id={pin_id or 'unknown'}")

    pinner = pin.get("pinner") if isinstance(pin.get("pinner"), dict) else {}
    creator = pin.get("native_creator") if isinstance(pin.get("native_creator"), dict) else {}
    attribution = pin.get("closeup_attribution") if isinstance(pin.get("closeup_attribution"), dict) else {}
    owner = pinner or creator or attribution

    owner_id = clean_text(owner.get("id")) or clean_text(owner.get("username")) or "unknown"
    owner_username = clean_text(owner.get("username"))
    owner_name = clean_text(owner.get("full_name") or owner.get("first_name")) or owner_username or "Unknown"
    owner_url = f"https://ru.pinterest.com/{owner_username}/" if owner_username else ""

    description = (
        clean_text(pin.get("description"))
        or clean_text(pin.get("closeup_unified_description"))
        or clean_text(pin.get("closeup_user_note"))
        or clean_text(pin.get("seo_alt_text"))
    )
    title = clean_text(pin.get("title")) or clean_text(pin.get("grid_title"))
    created_at = clean_text(pin.get("created_at"))

    upsell = state.get("upsell") if isinstance(state.get("upsell"), dict) else {}
    mweb = upsell.get("mWeb") if isinstance(upsell.get("mWeb"), dict) else {}
    views = safe_int(upsell.get("pinViewCount")) or safe_int(mweb.get("pinViewCount"))
    likes = safe_int(pin.get("favorite_user_count"))
    comments = safe_int(pin.get("comment_count"))
    shares = safe_int(pin.get("share_count"))
    repins = safe_int(pin.get("repin_count"))

    image_url = ""
    images = pin.get("images")
    if isinstance(images, dict):
        orig = images.get("orig") if isinstance(images.get("orig"), dict) else {}
        image_url = clean_text(orig.get("url"))
        if not image_url:
            for key in ("1200x", "736x", "564x", "474x", "236x"):
                item = images.get(key)
                if isinstance(item, dict):
                    image_url = clean_text(item.get("url"))
                    if image_url:
                        break

    return {
        "url": source_url,
        "pin_id": clean_text(pin.get("id")) or pin_id,
        "owner_id": owner_id,
        "owner_name": owner_name,
        "owner_username": owner_username,
        "owner_url": owner_url,
        "owner_avatar": clean_text(owner.get("image_medium_url") or owner.get("image_small_url")),
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "reposts": repins,
        "date_published_raw": created_at,
        "date_published_display": format_date(created_at),
        "description": description,
        "title": title,
        "image_url": image_url,
        "parse_status": "ok",
    }


def fetch_items(urls, cookie_header, pause, verbose=False, force_playwright_redirect=False):
    session = requests.Session()
    items = []
    for index, url in enumerate(urls, start=1):
        if verbose:
            log(f"Fetching {index} / {len(urls)} | {url}")
        try:
            resolved_url = resolve_short_url_requests(session, url, cookie_header)
            if is_pin_short_url(url) and not extract_pin_id(resolved_url) and force_playwright_redirect:
                try:
                    resolved_url = resolve_short_url_playwright(url, cookie_header, headless=True)
                except Exception as pw_exc:
                    if verbose:
                        log(f"[PW REDIRECT ERROR] {url}: {pw_exc}")

            response = session.get(resolved_url, headers=make_headers(resolved_url, cookie_header), timeout=45, allow_redirects=True)
            response.raise_for_status()
            final_url = normalize_pin_url(response.url or resolved_url)
            item = parse_pin(response.text, final_url)
            item["source_index"] = index
            items.append(item)
        except Exception as exc:
            pin_id = extract_pin_id(url)
            items.append({
                "url": url,
                "pin_id": pin_id,
                "owner_id": "error",
                "owner_name": "ERROR",
                "owner_username": "",
                "owner_url": "",
                "owner_avatar": "",
                "views": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "reposts": 0,
                "date_published_raw": "",
                "date_published_display": "",
                "description": f"ERROR: {exc}",
                "title": "",
                "image_url": "",
                "parse_status": "error",
                "source_index": index,
            })
        if pause > 0 and index < len(urls):
            time.sleep(pause)
    return items


def build_owner_summary(items):
    owners = {}
    for item in items:
        key = item.get("owner_username") or item.get("owner_id") or item.get("owner_name") or "unknown"
        if key not in owners:
            owners[key] = {
                "owner_name": item.get("owner_name", ""),
                "owner_username": item.get("owner_username", ""),
                "owner_url": item.get("owner_url", ""),
                "owner_avatar": item.get("owner_avatar", ""),
                "videos_count": 0,
                "views_sum": 0,
                "likes_sum": 0,
                "comments_sum": 0,
                "shares_sum": 0,
            }
        owners[key]["videos_count"] += 1
        owners[key]["views_sum"] += safe_int(item.get("views"))
        owners[key]["likes_sum"] += safe_int(item.get("likes"))
        owners[key]["comments_sum"] += safe_int(item.get("comments"))
        owners[key]["shares_sum"] += safe_int(item.get("shares"))
    return sorted(owners.values(), key=lambda x: x["views_sum"], reverse=True)


def build_owner_rows(items):
    rows = []
    for owner in build_owner_summary(items):
        avg_views = round(owner["views_sum"] / owner["videos_count"]) if owner["videos_count"] else 0
        avatar = ""
        if owner.get("owner_avatar"):
            avatar = f'<img class="owner-avatar" src="{html.escape(owner["owner_avatar"], quote=True)}">'
        rows.append(f"""
        <tr>
            <td>
                <div class="owner-cell">
                    {avatar}
                    <div>
                        <a href="{html.escape(owner.get("owner_url") or "", quote=True)}" target="_blank">
                            <strong>{html.escape(owner.get("owner_name") or "")}</strong>
                        </a>
                        <div class="muted">@{html.escape(owner.get("owner_username") or "")}</div>
                    </div>
                </div>
            </td>
            <td>{owner["videos_count"]}</td>
            <td>{owner["views_sum"]}</td>
            <td>{avg_views}</td>
            <td>{owner["likes_sum"]}</td>
            <td>{owner["comments_sum"]}</td>
            <td>{owner["shares_sum"]}</td>
        </tr>
        """)
    return "\n".join(rows)


def build_video_rows(items):
    rows = []
    for item in items:
        search = html.escape(
            f'{item.get("description","")} {item.get("owner_name","")} {item.get("owner_username","")} {item.get("pin_id","")} {item.get("url","")}'.lower(),
            quote=True,
        )
        avatar = ""
        if item.get("owner_avatar"):
            avatar = f'<img class="owner-avatar" src="{html.escape(item["owner_avatar"], quote=True)}">'
        thumb = ""
        if item.get("image_url"):
            thumb = f'<img class="thumb" src="{html.escape(item["image_url"], quote=True)}">'
        rows.append(f"""
        <tr class="data-row" data-search="{search}" data-views="{safe_int(item.get("views"))}" data-manually-hidden="0">
            <td><input type="checkbox" class="row-check"></td>
            <td>{item.get("source_index", "")}</td>
            <td>{html.escape(item.get("date_published_display") or "")}</td>
            <td>{safe_int(item.get("views"))}</td>
            <td>
                <div class="owner-cell">
                    {avatar}
                    <div>
                        <a href="{html.escape(item.get("owner_url") or "", quote=True)}" target="_blank">
                            <strong>{html.escape(item.get("owner_name") or "")}</strong>
                        </a>
                        <div class="muted">@{html.escape(item.get("owner_username") or "")}</div>
                        <div class="muted">status: {html.escape(item.get("parse_status") or "")}</div>
                    </div>
                </div>
            </td>
            <td><a href="{html.escape(item.get("url") or "", quote=True)}" target="_blank">{html.escape(item.get("url") or "")}</a></td>
            <td>{html.escape(item.get("pin_id") or "")}</td>
            <td>{safe_int(item.get("likes"))}</td>
            <td>{safe_int(item.get("comments"))}</td>
            <td>{safe_int(item.get("shares"))}</td>
            <td>{thumb}</td>
            <td class="description-cell">{html.escape(item.get("description") or item.get("title") or "")}</td>
        </tr>
        """)
    return "\n".join(rows)


def render_html(items, title):
    restart_url = os.getenv("WOW_UI_URL", "http://127.0.0.1:8765/")
    total_views = sum(safe_int(i.get("views")) for i in items)
    total_owners = len({i.get("owner_username") or i.get("owner_id") or i.get("owner_name") for i in items})
    owner_rows = build_owner_rows(items)
    video_rows = build_video_rows(items)
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<link rel="icon" type="image/png" href="favicon.png">
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
.owner-cell {{ display:flex; gap:10px; align-items:center; min-width:220px; }}
.owner-avatar {{ width:42px; height:42px; border-radius:50%; object-fit:cover; background:#e5e7eb; }}
.thumb {{ width:120px; border-radius:8px; }}
.muted {{ color:#667085; font-size:12px; margin-top:3px; }}
a {{ color:#1d4ed8; text-decoration:none; word-break:break-all; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<p><a href="{html.escape(restart_url, quote=True)}" style="display:inline-block;padding:8px 12px;border:1px solid #c7d2e0;border-radius:10px;background:#eef3f8;color:#1f2937;text-decoration:none;font-weight:600;">Парсить заново</a></p>
<div class="toolbar">
    <div>
        <label for="searchFilter"><b>Фильтр:</b></label><br>
        <input type="text" id="searchFilter" placeholder="Автор, описание, ссылка или Pin ID">
    </div>
    <div>
        <button type="button" id="hideSelectedBtn">Скрыть выделенные</button>
        <button type="button" id="showAllHiddenBtn">Показать все скрытые</button>
    </div>
    <div class="stat-box">Всего пинов: <strong id="totalCount">{len(items)}</strong></div>
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
<th>Автор</th><th>Пинов</th><th>Просмотры</th><th>Средние просмотры</th><th>Лайки</th><th>Комментарии</th><th>Репосты</th>
</tr>
</thead>
<tbody>{owner_rows}</tbody>
</table>
<h2>Детализация по пинам</h2>
<table>
<thead>
<tr>
<th><input type="checkbox" id="checkAllVisible"></th>
<th>#</th><th>Дата публикации</th><th>Просмотры</th><th>Автор</th><th>Ссылка</th><th>Pin ID</th><th>Лайки</th><th>Комментарии</th><th>Репосты</th><th>Превью</th><th>Описание</th>
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
    parser = argparse.ArgumentParser(description="Pinterest parser grouped by author")
    parser.add_argument("--input", default="pinterest.txt")
    parser.add_argument("--output", default="index.html")
    parser.add_argument("--title", default="Pinterest Pins")
    parser.add_argument("--cookie", default="")
    parser.add_argument("--cookie-file", default="pinterest_token.txt")
    parser.add_argument("--save-json", default="")
    parser.add_argument("--pause", type=float, default=0.2)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--force-playwright-redirect", action="store_true")
    args = parser.parse_args()

    urls = load_urls(args.input)
    if not urls:
        raise RuntimeError(f"Файл пустой: {args.input}")

    cookie_header = clean_text(args.cookie)
    if not cookie_header and args.cookie_file and Path(args.cookie_file).exists():
        cookie_header = Path(args.cookie_file).read_text(encoding="utf-8").strip()
    if not cookie_header:
        cookie_header = os.environ.get("PINTEREST_COOKIE", "").strip()
    if not cookie_header:
        raise RuntimeError("Pinterest cookie/token не указан. Заполни поле Pinterest token/cookie в UI.")

    items = fetch_items(
        urls,
        cookie_header=cookie_header,
        pause=args.pause,
        verbose=args.verbose,
        force_playwright_redirect=args.force_playwright_redirect,
    )
    Path(args.output).write_text(render_html(items, args.title), encoding="utf-8")
    if args.save_json:
        Path(args.save_json).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"HTML saved to {args.output}")


if __name__ == "__main__":
    main()
