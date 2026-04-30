#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import datetime as dt
import html
import json
import os
import shlex
import re
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


def format_timestamp(timestamp):
    if not timestamp:
        return ""
    try:
        parsed = dt.datetime.fromtimestamp(int(timestamp))
        return f"{parsed.day:02d} {MONTHS_RU.get(parsed.month, parsed.month)} {parsed.year}"
    except Exception:
        return ""


def extract_video_id(value):
    text = clean_text(value)
    for pattern in (r"/video/(\d+)", r"video/(\d+)", r"(\d{15,})"):
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return ""


def extract_username(value):
    text = clean_text(value)
    try:
        path = urlparse(text).path
        m = re.search(r"/@([^/]+)", path)
        if m:
            return m.group(1)
    except Exception:
        pass

    m = re.search(r"@([A-Za-z0-9._-]+)", text)
    return m.group(1) if m else ""


def normalize_input_url(line):
    raw = clean_text(line).strip().strip("'\"")

    m = re.search(r"https?://[^\s'\"<>]+", raw)
    if m:
        raw = m.group(0)

    if not raw:
        return ""

    parsed = urlparse(raw)
    host = parsed.netloc.lower()

    # короткие ссылки НЕ переписываем до браузера/редиректа
    if host in ("vt.tiktok.com", "vm.tiktok.com"):
        return raw

    username = extract_username(raw)
    video_id = extract_video_id(raw)

    if username and video_id:
        return f"https://www.tiktok.com/@{username}/video/{video_id}"

    if raw.startswith("http"):
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    return raw


def is_short_url(url):
    try:
        return urlparse(url).netloc.lower() in ("vt.tiktok.com", "vm.tiktok.com")
    except Exception:
        return False



def parse_curl_file(path):
    """
    Читает curl.txt целиком и вытаскивает:
    - первый URL;
    - headers из -H;
    - cookies из -b;
    - user-agent/referer/accept-language и т.д.

    Поддерживает curl в многострочном формате с backslash.
    """
    if not path:
        return {
            "url": "",
            "headers": {},
            "cookie": "",
            "referer": "",
            "user_agent": "",
        }

    text = Path(path).read_text(encoding="utf-8")
    normalized = text.replace("\\\n", " ")

    try:
        parts = shlex.split(normalized)
    except Exception:
        parts = normalized.split()

    result = {
        "url": "",
        "headers": {},
        "cookie": "",
        "referer": "",
        "user_agent": "",
    }

    i = 0
    while i < len(parts):
        part = parts[i]

        if part == "curl" and i + 1 < len(parts):
            result["url"] = parts[i + 1]
            i += 2
            continue

        if part in ("-H", "--header") and i + 1 < len(parts):
            header_line = parts[i + 1]

            if ":" in header_line:
                name, value = header_line.split(":", 1)
                name = name.strip()
                value = value.strip()

                if name:
                    result["headers"][name.lower()] = value

                    if name.lower() == "referer":
                        result["referer"] = value

                    if name.lower() == "user-agent":
                        result["user_agent"] = value

            i += 2
            continue

        if part in ("-b", "--cookie", "--cookie-jar") and i + 1 < len(parts):
            result["cookie"] = parts[i + 1].strip()
            i += 2
            continue

        i += 1

    return result


def merge_curl_headers(default_headers, curl_profile, url):
    headers = dict(default_headers)

    curl_headers = curl_profile.get("headers") or {}

    for name, value in curl_headers.items():
        # requests/Playwright сами управляют host/content-length/compression
        if name.lower() in ("host", "content-length"):
            continue

        headers[name] = value

    if curl_profile.get("referer"):
        headers["referer"] = curl_profile["referer"]
    else:
        headers["referer"] = url

    if curl_profile.get("user_agent"):
        headers["user-agent"] = curl_profile["user_agent"]

    return headers


def make_headers(url, cookie_header=None, curl_profile=None):
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

    if curl_profile:
        headers = merge_curl_headers(headers, curl_profile, url)

    effective_cookie = cookie_header or ""
    if not effective_cookie and curl_profile:
        effective_cookie = curl_profile.get("cookie") or ""

    if effective_cookie:
        headers["cookie"] = effective_cookie.strip()

    return headers

def is_waf_page(text):
    head = text[:50000].lower()
    return (
        "slardar_us_waf" in head
        or "_wafchallengeid" in head
        or "please wait..." in head
        or "waforiginalreid" in head
    )


def extract_waf_real_url(text):
    m = re.search(r'<p\s+id=["\']rs["\']\s+class=["\']([^"\']+)["\']', text, flags=re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def extract_script_json_by_id(page_html, script_id):
    pattern = r'<script[^>]+id=["\']' + re.escape(script_id) + r'["\'][^>]*>(.*?)</script>'
    m = re.search(pattern, page_html, flags=re.I | re.S)
    if not m:
        return None

    raw = html.unescape(m.group(1).strip())

    try:
        return json.loads(raw)
    except Exception:
        return None


def extract_all_application_json(page_html):
    out = []

    for m in re.finditer(r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', page_html, flags=re.I | re.S):
        raw = html.unescape(m.group(1).strip())

        if not raw or raw.startswith('{"_r"'):
            continue

        try:
            out.append(json.loads(raw))
        except Exception:
            pass

    return out


def looks_like_video_item(obj):
    if not isinstance(obj, dict):
        return False

    has_id = bool(clean_text(obj.get("id", "")))
    has_author = isinstance(obj.get("author"), dict)
    has_stats = isinstance(obj.get("stats"), dict) or isinstance(obj.get("statsV2"), dict)
    has_desc = "desc" in obj or "contents" in obj

    return has_id and has_author and (has_stats or has_desc)


def iter_video_items(obj):
    if isinstance(obj, dict):
        if "webapp.video-detail" in obj:
            item = obj.get("webapp.video-detail", {}).get("itemInfo", {}).get("itemStruct", {})
            if isinstance(item, dict) and item:
                yield item

        for key in ("ItemModule", "itemModule"):
            module = obj.get(key)
            if isinstance(module, dict):
                for item in module.values():
                    if isinstance(item, dict):
                        yield item

        if looks_like_video_item(obj):
            yield obj

        for value in obj.values():
            yield from iter_video_items(value)

    elif isinstance(obj, list):
        for value in obj:
            yield from iter_video_items(value)


def find_video_item(data, video_id):
    candidates = list(iter_video_items(data))

    if video_id:
        for item in candidates:
            if clean_text(item.get("id")) == video_id:
                return item

    return candidates[0] if candidates else None


def parse_contents(item):
    parts = []

    contents = item.get("contents") or []

    if isinstance(contents, list):
        for c in contents:
            if isinstance(c, dict):
                desc = clean_text(c.get("desc", ""))
                if desc:
                    parts.append(desc)

    return "\n".join(parts).strip()


def make_item(url, video_id, owner_id, unique_id, nickname, avatar, views, likes, comments, shares, collects, reposts, create_time, desc, status="ok"):
    return {
        "url": url,
        "video_id": video_id,
        "owner_id": owner_id or unique_id or "unknown",
        "owner_name": nickname or unique_id or "Unknown",
        "owner_unique_id": unique_id or "",
        "owner_url": f"https://www.tiktok.com/@{unique_id}" if unique_id else "",
        "owner_avatar": avatar or "",
        "views": safe_int(views),
        "likes": safe_int(likes),
        "comments": safe_int(comments),
        "shares": safe_int(shares),
        "collects": safe_int(collects),
        "reposts": safe_int(reposts),
        "date_published_raw": create_time or "",
        "date_published_display": format_timestamp(create_time),
        "description": desc or "",
        "parse_status": status,
    }


def regex_window_parse(page_html, source_url):
    video_id = extract_video_id(source_url)
    pos = page_html.find(video_id) if video_id else -1

    if pos == -1:
        return None

    window = page_html[max(0, pos - 120000): pos + 320000]

    def grab(pattern):
        m = re.search(pattern, window, flags=re.S)
        return clean_text(m.group(1)) if m else ""

    unique_id = grab(r'"uniqueId"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"') or extract_username(source_url)
    nickname = grab(r'"nickname"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"') or unique_id or "Unknown"
    author_id = grab(r'"author"\s*:\s*\{.*?"id"\s*:\s*"(\d+)"') or unique_id or "unknown"

    views = safe_int(grab(r'"playCount"\s*:\s*"?(\d+)"?'))
    likes = safe_int(grab(r'"diggCount"\s*:\s*"?(\d+)"?'))
    comments = safe_int(grab(r'"commentCount"\s*:\s*"?(\d+)"?'))
    shares = safe_int(grab(r'"shareCount"\s*:\s*"?(\d+)"?'))
    collects = safe_int(grab(r'"collectCount"\s*:\s*"?(\d+)"?'))
    reposts = safe_int(grab(r'"repostCount"\s*:\s*"?(\d+)"?'))
    create_time = grab(r'"createTime"\s*:\s*"?(\d+)"?')
    desc = grab(r'"desc"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')

    if not (unique_id or views or desc):
        return None

    return make_item(source_url, video_id, author_id, unique_id, nickname, "", views, likes, comments, shares, collects, reposts, create_time, desc, "regex_window")


def parse_video_html(page_html, source_url):
    source_url = normalize_input_url(source_url)

    if is_waf_page(page_html):
        real_url = normalize_input_url(extract_waf_real_url(page_html) or source_url)
        username = extract_username(real_url)
        video_id = extract_video_id(real_url)

        return make_item(
            real_url,
            video_id,
            username or "waf_blocked",
            username,
            username or "WAF blocked",
            "",
            0, 0, 0, 0, 0, 0,
            "",
            "WAF_BLOCKED: TikTok отдал Please wait вместо HTML видео",
            "waf_blocked",
        )

    video_id = extract_video_id(source_url)

    data_sources = []

    for sid in ("__UNIVERSAL_DATA_FOR_REHYDRATION__", "__NEXT_DATA__", "SIGI_STATE"):
        data = extract_script_json_by_id(page_html, sid)
        if data:
            data_sources.append(data)

    data_sources.extend(extract_all_application_json(page_html))

    for data in data_sources:
        item = find_video_item(data, video_id)

        if not item:
            continue

        author = item.get("author") or {}
        if not isinstance(author, dict):
            author = {}

        stats = item.get("stats") or {}
        stats_v2 = item.get("statsV2") or {}

        if not isinstance(stats, dict):
            stats = {}

        if not isinstance(stats_v2, dict):
            stats_v2 = {}

        vid = clean_text(item.get("id")) or video_id
        unique_id = clean_text(author.get("uniqueId")) or clean_text(author.get("unique_id")) or extract_username(source_url)
        nickname = clean_text(author.get("nickname")) or clean_text(author.get("nickName")) or unique_id or "Unknown"
        owner_id = clean_text(author.get("id")) or clean_text(author.get("uid")) or clean_text(author.get("userId")) or unique_id or "unknown"
        avatar = clean_text(author.get("avatarThumb")) or clean_text(author.get("avatarMedium")) or clean_text(author.get("avatarLarger"))

        views = safe_int(stats_v2.get("playCount")) or safe_int(stats.get("playCount")) or safe_int(item.get("playCount"))
        likes = safe_int(stats_v2.get("diggCount")) or safe_int(stats.get("diggCount"))
        comments = safe_int(stats_v2.get("commentCount")) or safe_int(stats.get("commentCount"))
        shares = safe_int(stats_v2.get("shareCount")) or safe_int(stats.get("shareCount"))
        collects = safe_int(stats_v2.get("collectCount")) or safe_int(stats.get("collectCount"))
        reposts = safe_int(stats_v2.get("repostCount")) or safe_int(stats.get("repostCount"))
        create_time = clean_text(item.get("createTime")) or clean_text(item.get("create_time"))
        desc = parse_contents(item) or clean_text(item.get("desc"))

        return make_item(
            source_url, vid, owner_id, unique_id, nickname, avatar,
            views, likes, comments, shares, collects, reposts, create_time, desc, "ok"
        )

    fallback = regex_window_parse(page_html, source_url)

    if fallback:
        return fallback

    username = extract_username(source_url)
    video_id = extract_video_id(source_url)

    return make_item(
        source_url,
        video_id,
        username or "not_found",
        username,
        username or "Unknown",
        "",
        0, 0, 0, 0, 0, 0,
        "",
        "ERROR: video JSON not found",
        "not_found",
    )


def parse_cookie_header(cookie_header, domain=".tiktok.com"):
    cookies = []

    if not cookie_header:
        return cookies

    for part in cookie_header.split(";"):
        if "=" not in part:
            continue

        name, value = part.strip().split("=", 1)

        if name:
            cookies.append({
                "name": name.strip(),
                "value": value.strip(),
                "domain": domain,
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            })

    return cookies


def fetch_with_playwright(context, url, wait_ms=12000, retries=2):
    log(f"[PW] OPEN {url}")

    last_content = ""
    last_url = url
    target_video_id = extract_video_id(url)

    for attempt in range(1, retries + 1):
        page = context.new_page()

        try:
            try:
                page.goto(url, wait_until="commit", timeout=60000)
            except Exception as e:
                log(f"[PW] goto warning attempt {attempt}/{retries}: {e}")

            # Ждем не фиксированные 9-60 секунд, а появления нужных данных в HTML.
            # Как только hydration JSON появился — сразу забираем content.
            deadline_ms = wait_ms
            step_ms = 500
            elapsed = 0

            content = ""

            while elapsed < deadline_ms:
                page.wait_for_timeout(step_ms)
                elapsed += step_ms

                content = page.content()
                final_url = normalize_input_url(page.url or url)

                has_video_data = (
                    "webapp.video-detail" in content
                    or "__UNIVERSAL_DATA_FOR_REHYDRATION__" in content
                    or "SIGI_STATE" in content
                    or '"playCount"' in content
                    or '"statsV2"' in content
                )

                has_target_id = bool(target_video_id and target_video_id in content)

                if has_video_data and (has_target_id or not target_video_id):
                    log(f"[PW] data found after {elapsed}ms")
                    return content, final_url

                # Если WAF — не ждём весь таймер молча, но даём шанс странице продолжить.
                if is_waf_page(content):
                    if elapsed == step_ms:
                        log("[PW] WAF visible, waiting for challenge/result...")

            final_url = normalize_input_url(page.url or url)
            last_content = content or page.content()
            last_url = final_url

            # Если после ожидания WAF всё ещё на месте — даём ручное окно,
            # но только после того, как быстрый поиск данных не сработал.
            if is_waf_page(last_content):
                log("[PW] WAF still visible. You have 60 seconds to pass check manually in opened Chromium.")

                for _ in range(12):
                    page.wait_for_timeout(5000)
                    content = page.content()
                    final_url = normalize_input_url(page.url or final_url)

                    has_video_data = (
                        "webapp.video-detail" in content
                        or "__UNIVERSAL_DATA_FOR_REHYDRATION__" in content
                        or "SIGI_STATE" in content
                        or '"playCount"' in content
                        or '"statsV2"' in content
                    )

                    has_target_id = bool(target_video_id and target_video_id in content)

                    if not is_waf_page(content) and has_video_data and (has_target_id or not target_video_id):
                        log("[PW] WAF passed and data found")
                        return content, final_url

                return content, final_url

            log(f"[PW] timeout waiting data after {deadline_ms}ms, returning current html")
            return last_content, last_url

        except Exception as e:
            log(f"[PW] page error attempt {attempt}/{retries}: {e}")

            if attempt == retries:
                if last_content:
                    return last_content, last_url
                raise

        finally:
            page.close()

        time.sleep(1)

    return last_content, last_url

def resolve_short_url_requests(session, url, cookie_header=None, curl_profile=None):
    cleaned = normalize_input_url(url)

    if not is_short_url(cleaned):
        return cleaned

    log(f"[REDIRECT] requests resolving {cleaned}")

    r = session.get(
        cleaned,
        headers=make_headers(cleaned, cookie_header, curl_profile=curl_profile),
        timeout=40,
        allow_redirects=True,
    )

    r.raise_for_status()

    final_url = normalize_input_url(r.url or cleaned)
    log(f"[REDIRECT] {cleaned} -> {final_url}")

    return final_url


def load_cookie_header(path):
    if not path:
        return ""

    return Path(path).read_text(encoding="utf-8").strip()



def parse_headers_file(path):
    """
    Понимает файл формата copy-as-curl без URL:

      -H 'accept: text/html,...' \
      -H 'user-agent: Mozilla/5.0 ...' \
      -b 'a=1; b=2' \

    Возвращает:
      headers: dict
      cookie_header: str
    """
    if not path:
        return {}, ""

    raw = Path(path).read_text(encoding="utf-8").strip()

    if not raw:
        return {}, ""

    # Склеиваем многострочный curl-фрагмент.
    normalized = raw.replace("\\\n", " ")
    normalized = normalized.replace("\\\r\n", " ")

    try:
        tokens = shlex.split(normalized)
    except Exception:
        # fallback: грубый парсинг regex-ами
        tokens = []

    headers = {}
    cookie_header = ""

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

            if token in ("-b", "--cookie", "--cookie-jar") and i + 1 < len(tokens):
                cookie_header = tokens[i + 1].strip()
                i += 2
                continue

            i += 1

    else:
        # Regex fallback для строк вида -H 'key: value' и -b '...'
        for match in re.finditer(r"-H\s+(['\"])(.*?)\1", normalized, flags=re.S):
            header_line = match.group(2)
            if ":" in header_line:
                key, value = header_line.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        match = re.search(r"-b\s+(['\"])(.*?)\1", normalized, flags=re.S)
        if match:
            cookie_header = match.group(2).strip()

    return headers, cookie_header


def merge_headers(default_headers, curl_headers):
    """
    curl headers имеют приоритет, но host/content-length не переносим.
    """
    result = dict(default_headers or {})

    skip = {
        "host",
        "content-length",
        "connection",
        "accept-encoding",
    }

    for key, value in (curl_headers or {}).items():
        lk = key.lower().strip()
        if lk in skip:
            continue
        result[lk] = value

    return result


def load_urls(path):
    rows = Path(path).read_text(encoding="utf-8").splitlines()
    urls = []

    seen = set()

    for row in rows:
        url = normalize_input_url(row)

        if not url or url in seen:
            continue

        seen.add(url)
        urls.append(url)

    return urls


def fetch_items_requests(urls, cookie_header, pause, debug_html_dir, verbose, curl_profile=None):
    session = requests.Session()
    items = []

    for index, url in enumerate(urls, start=1):
        log(f"Fetching {index} / {len(urls)} | {url}")

        try:
            final_url = resolve_short_url_requests(session, url, cookie_header, curl_profile=curl_profile)

            page_html = ""
            status_code = 0

            for waf_attempt in range(1, 6):
                r = session.get(
                    final_url,
                    headers=make_headers(final_url, cookie_header, curl_profile=curl_profile),
                    timeout=40,
                    allow_redirects=True,
                )

                page_html = r.text
                status_code = r.status_code
                final_url = normalize_input_url(r.url or final_url)

                if not is_waf_page(page_html):
                    break

                log(f"[WAF-REQUESTS] Please wait page, attempt {waf_attempt}/5. Sleep 5s: {final_url}")

                # requests.Session сохраняет Set-Cookie автоматически.
                # TikTok иногда после challenge начинает отдавать нормальную страницу не сразу.
                time.sleep(5)

            if debug_html_dir and (is_waf_page(page_html) or status_code >= 400):
                Path(debug_html_dir).mkdir(parents=True, exist_ok=True)
                Path(debug_html_dir, f"{index}_{extract_video_id(final_url) or 'unknown'}.html").write_text(page_html, encoding="utf-8")

            item = parse_video_html(page_html, final_url)
            item["url"] = url
            item["parsed_url"] = final_url
            item["source_index"] = index
            item["http_status"] = status_code
            items.append(item)

        except Exception as e:
            username = extract_username(url)
            video_id = extract_video_id(url)

            items.append({
                "url": url,
                "video_id": video_id,
                "owner_id": username or "error",
                "owner_name": username or "ERROR",
                "owner_unique_id": username,
                "owner_url": f"https://www.tiktok.com/@{username}" if username else "",
                "owner_avatar": "",
                "views": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "collects": 0,
                "reposts": 0,
                "date_published_raw": "",
                "date_published_display": "",
                "description": f"ERROR: {e}",
                "parse_status": "error",
                "source_index": index,
            })

        if pause > 0 and index < len(urls):
            time.sleep(pause)

    return items


def create_playwright_context(cookie_header, profile_dir, headless=False, proxy_server="", curl_profile=None):
    log("[PW] import playwright")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise RuntimeError("Playwright не импортируется. Проверь: python3.14 -c \"import playwright\"") from e

    pw = sync_playwright().start()

    log("[PW] launch Chromium persistent context")

    launch_kwargs = {}

    if proxy_server:
        launch_kwargs["proxy"] = {"server": proxy_server}

    curl_profile = curl_profile or {}
    extra_headers = curl_profile.get("headers", {}) or {}

    ua = extra_headers.get("user-agent") or (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )
    accept_language = extra_headers.get("accept-language") or "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    locale = accept_language.split(",")[0].strip() or "ru-RU"

    playwright_extra_headers = {
        k: v for k, v in extra_headers.items()
        if k not in {
            "cookie",
            "user-agent",
            "host",
            "content-length",
            "connection",
            "accept-encoding",
            "upgrade-insecure-requests",
        }
    }

    context = pw.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=headless,
        viewport={"width": 1440, "height": 1000},
        locale=locale,
        ignore_https_errors=True,
        java_script_enabled=True,
        bypass_csp=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
        user_agent=(
            (curl_profile or {}).get("user_agent")
            or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        extra_http_headers={
            k: v for k, v in ((curl_profile or {}).get("headers") or {}).items()
            if k.lower() not in ("host", "cookie", "content-length", "user-agent")
        },
        **launch_kwargs,
    )

    effective_cookie = cookie_header or ((curl_profile or {}).get("cookie") or "")

    if effective_cookie:
        cookies = parse_cookie_header(effective_cookie)

        if cookies:
            log(f"[PW] add cookies: {len(cookies)}")
            context.add_cookies(cookies)

    return pw, context


def install_playwright_chromium():
    from playwright.__main__ import main as playwright_main
    old_argv = sys.argv[:]
    try:
        sys.argv = ["playwright", "install", "chromium"]
        playwright_main()
    finally:
        sys.argv = old_argv


def fetch_items_playwright(urls, cookie_header, pause, debug_html_dir, verbose, profile_dir, headless, proxy_server="", curl_profile=None, playwright_wait_ms=12000):
    log("[MODE] FORCE PLAYWRIGHT ENABLED")
    try:
        pw, context = create_playwright_context(cookie_header, profile_dir, headless=headless, proxy_server=proxy_server, curl_profile=curl_profile)
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            log("[PW] browser executable missing, installing chromium...")
            install_playwright_chromium()
            pw, context = create_playwright_context(cookie_header, profile_dir, headless=headless, proxy_server=proxy_server, curl_profile=curl_profile)
        else:
            raise

    items = []

    try:
        for index, url in enumerate(urls, start=1):
            log(f"Fetching {index} / {len(urls)} | {url}")

            try:
                # Для vt/vm лучше дать браузеру самому пройти редирект.
                page_html, final_url = fetch_with_playwright(context, url, wait_ms=playwright_wait_ms)

                if debug_html_dir and is_waf_page(page_html):
                    Path(debug_html_dir).mkdir(parents=True, exist_ok=True)
                    Path(debug_html_dir, f"{index}_{extract_video_id(final_url) or 'unknown'}_waf.html").write_text(page_html, encoding="utf-8")

                item = parse_video_html(page_html, final_url)
                item["url"] = url
                item["parsed_url"] = final_url
                item["source_index"] = index
                items.append(item)

                log(f"[OK] {item.get('owner_unique_id')} | views={item.get('views')} | status={item.get('parse_status')}")

            except Exception as e:
                username = extract_username(url)
                video_id = extract_video_id(url)

                log(f"[ERROR] {url}: {e}")

                items.append({
                    "url": url,
                    "video_id": video_id,
                    "owner_id": username or "error",
                    "owner_name": username or "ERROR",
                    "owner_unique_id": username,
                    "owner_url": f"https://www.tiktok.com/@{username}" if username else "",
                    "owner_avatar": "",
                    "views": 0,
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "collects": 0,
                    "reposts": 0,
                    "date_published_raw": "",
                    "date_published_display": "",
                    "description": f"ERROR: {e}",
                    "parse_status": "error",
                    "source_index": index,
                })

            if pause > 0 and index < len(urls):
                time.sleep(pause)

    finally:
        context.close()
        pw.stop()

    return items


def build_owner_summary(items):
    owners = {}

    for item in items:
        key = item.get("owner_unique_id") or item.get("owner_id") or item.get("owner_name") or "unknown"

        if key not in owners:
            owners[key] = {
                "owner_id": item.get("owner_id", ""),
                "owner_name": item.get("owner_name", ""),
                "owner_unique_id": item.get("owner_unique_id", ""),
                "owner_url": item.get("owner_url", ""),
                "owner_avatar": item.get("owner_avatar", ""),
                "videos_count": 0,
                "views_sum": 0,
                "likes_sum": 0,
                "comments_sum": 0,
                "shares_sum": 0,
                "collects_sum": 0,
            }

        owners[key]["videos_count"] += 1
        owners[key]["views_sum"] += safe_int(item.get("views"))
        owners[key]["likes_sum"] += safe_int(item.get("likes"))
        owners[key]["comments_sum"] += safe_int(item.get("comments"))
        owners[key]["shares_sum"] += safe_int(item.get("shares"))
        owners[key]["collects_sum"] += safe_int(item.get("collects"))

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
                        <div class="muted">@{html.escape(owner.get("owner_unique_id") or "")}</div>
                        <div class="muted">ID {html.escape(str(owner.get("owner_id") or ""))}</div>
                    </div>
                </div>
            </td>
            <td>{owner["videos_count"]}</td>
            <td>{owner["views_sum"]}</td>
            <td>{avg_views}</td>
            <td>{owner["likes_sum"]}</td>
            <td>{owner["comments_sum"]}</td>
            <td>{owner["shares_sum"]}</td>
            <td>{owner["collects_sum"]}</td>
        </tr>
        """)

    return "\n".join(rows)


def build_video_rows(items):
    rows = []

    for item in items:
        avatar = ""
        if item.get("owner_avatar"):
            avatar = f'<img class="owner-avatar" src="{html.escape(item["owner_avatar"], quote=True)}">'

        search = html.escape(
            f'{item.get("description","")} {item.get("owner_name","")} {item.get("owner_unique_id","")} {item.get("video_id","")} {item.get("url","")}'.lower(),
            quote=True,
        )

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
                        <div class="muted">@{html.escape(item.get("owner_unique_id") or "")}</div>
                        <div class="muted">status: {html.escape(item.get("parse_status") or "")}</div>
                    </div>
                </div>
            </td>
            <td><a href="{html.escape(item.get("url") or "", quote=True)}" target="_blank">{html.escape(item.get("url") or "")}</a></td>
            <td>{html.escape(item.get("video_id") or "")}</td>
            <td>{safe_int(item.get("likes"))}</td>
            <td>{safe_int(item.get("comments"))}</td>
            <td>{safe_int(item.get("shares"))}</td>
            <td>{safe_int(item.get("collects"))}</td>
            <td class="description-cell">{html.escape(item.get("description") or "")}</td>
        </tr>
        """)

    return "\n".join(rows)


def render_html(items, title):
    restart_url = os.getenv("WOW_UI_URL", "http://127.0.0.1:8765/")
    total_views = sum(safe_int(i.get("views")) for i in items)
    total_owners = len({i.get("owner_unique_id") or i.get("owner_id") or i.get("owner_name") for i in items})

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
        <input type="text" id="searchFilter" placeholder="Автор, описание, ссылка или Video ID">
    </div>
    <div>
        <button type="button" id="hideSelectedBtn">Скрыть выделенные</button>
        <button type="button" id="showAllHiddenBtn">Показать все скрытые</button>
    </div>
    <div class="stat-box">Всего видео: <strong id="totalCount">{len(items)}</strong></div>
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
<th>Автор</th><th>Видео</th><th>Просмотры</th><th>Средние просмотры</th><th>Лайки</th><th>Комментарии</th><th>Репосты</th><th>Сохранения</th>
</tr>
</thead>
<tbody>{owner_rows}</tbody>
</table>

<h2>Детализация по видео</h2>
<table>
<thead>
<tr>
<th><input type="checkbox" id="checkAllVisible"></th>
<th>#</th><th>Дата публикации</th><th>Просмотры</th><th>Автор</th><th>Ссылка</th><th>Video ID</th><th>Лайки</th><th>Комментарии</th><th>Репосты</th><th>Сохранения</th><th>Описание</th>
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
    parser = argparse.ArgumentParser(description="TikTok parser grouped by author")
    parser.add_argument("--input", default="tiktok.txt")
    parser.add_argument("--output", default="index.html")
    parser.add_argument("--title", default="TikTok Videos")
    parser.add_argument("--cookie-file", default="")
    parser.add_argument("--headers-file", default="", help="Файл с copy-as-curl headers: строки -H и -b")
    parser.add_argument("--curl-file", default="", help="Файл с полным curl-запросом TikTok. Скрипт возьмет оттуда headers, cookies, user-agent, referer")
    parser.add_argument("--cookie", default="")
    parser.add_argument("--save-json", default="")
    parser.add_argument("--pause", type=float, default=0)
    parser.add_argument("--debug-html-dir", default="")
    parser.add_argument("--force-playwright", action="store_true")
    parser.add_argument("--playwright-profile", default="tiktok_profile")
    parser.add_argument("--playwright-wait-ms", type=int, default=12000, help="Max wait for TikTok hydration data in Playwright")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--proxy", default="", help="Proxy for Playwright, example: http://user:pass@host:port")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    urls = load_urls(args.input)

    if not urls:
        raise RuntimeError(f"input is empty: {args.input}")

    curl_profile = parse_curl_file(args.curl_file) if args.curl_file else {}

    cookie_header = args.cookie or load_cookie_header(args.cookie_file) or (curl_profile.get("cookie") if curl_profile else "")

    if args.force_playwright:
        items = fetch_items_playwright(
            urls=urls,
            cookie_header=cookie_header,
            pause=args.pause,
            debug_html_dir=args.debug_html_dir,
            verbose=args.verbose,
            profile_dir=args.playwright_profile,
            headless=args.headless,
            proxy_server=args.proxy,
            curl_profile=curl_profile,
            playwright_wait_ms=args.playwright_wait_ms,
        )
    else:
        items = fetch_items_requests(
            urls=urls,
            cookie_header=cookie_header,
            pause=args.pause,
            debug_html_dir=args.debug_html_dir,
            verbose=args.verbose,
            curl_profile=curl_profile,
        )

    Path(args.output).write_text(render_html(items, args.title), encoding="utf-8")

    if args.save_json:
        Path(args.save_json).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"HTML saved to {args.output}")


if __name__ == "__main__":
    main()
