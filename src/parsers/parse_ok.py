#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Парсинг OK.ru: Playwright + блок VideoLayerPins; резерв — meta/HTML. Отчёт как у TikTok (группировка по авторам)."""

from __future__ import annotations

import argparse
import datetime as dt
import html as html_module
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

from src.core.urls_splitter import extract_ok_video_id, normalize_url


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


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    text = html_module.unescape(str(value))
    text = text.replace("\\u002F", "/").replace("\\/", "/")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def safe_int(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return int(re.sub(r"[^\d]", "", str(value)))
    except Exception:
        return 0


def extract_video_id(url: str) -> str:
    return extract_ok_video_id(clean_text(url)) or ""


def normalize_ok_url(line: str) -> str:
    raw = clean_text(line).strip().strip("'\"")
    m = re.search(r"https?://[^\s'\"<>]+", raw)
    if m:
        raw = m.group(0)
    if not raw:
        return ""
    return normalize_url(raw)


def load_urls(path: str | Path) -> list[str]:
    rows = Path(path).read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in rows:
        u = normalize_ok_url(line)
        if u:
            out.append(u)
    seen: set[str] = set()
    unique: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def extract_meta_property(page_html: str, prop: str) -> str:
    pat1 = re.compile(
        r'<meta[^>]+property=["\']' + re.escape(prop) + r'["\'][^>]*content=["\']([^"\']*)["\']',
        re.I | re.S,
    )
    m = pat1.search(page_html)
    if m:
        return clean_text(html_module.unescape(m.group(1)))
    pat2 = re.compile(
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*property=["\']' + re.escape(prop) + r'["\']',
        re.I | re.S,
    )
    m = pat2.search(page_html)
    if m:
        return clean_text(html_module.unescape(m.group(1)))
    return extract_meta_property_loose(page_html, prop)


def extract_meta_property_loose(page_html: str, prop: str) -> str:
    esc = re.escape(prop)
    patterns = [
        rf'property\s*=\s*["\']{esc}["\']\s+content\s*=\s*["\']([^"\']*)["\']',
        rf'content\s*=\s*["\']([^"\']*)["\']\s+property\s*=\s*["\']{esc}["\']',
    ]
    for p in patterns:
        m = re.search(p, page_html, re.I | re.S)
        if m:
            return clean_text(html_module.unescape(m.group(1)))
    return ""


def extract_profile_url(page_html: str) -> str:
    m = re.search(r'https?://(?:www\.)?ok\.ru/profile/\d+', page_html)
    return m.group(0).split("?", 1)[0].rstrip("/") if m else ""


def extract_profile_id(page_html: str) -> str:
    m = re.search(r'ok\.ru/profile/(\d+)', page_html)
    return m.group(1) if m else ""


def views_from_visible_html(page_html: str) -> int:
    chunk = page_html[:200000]
    m = re.search(
        r"(?<!\w)(\d[\d\s\u00A0\u202F]*)\s*просмотр(?:а|ов)?(?!\w)",
        chunk,
        re.I,
    )
    if not m:
        m = re.search(
            r"([\d\s\u00A0\u202F]+)\s*просмотр",
            chunk,
            re.I,
        )
    if not m:
        return 0
    return safe_int(m.group(1))


def views_from_embedded_json(page_html: str) -> int:
    for pat in (
        r'"watchCount"\s*:\s*(\d+)',
        r'"views_total"\s*:\s*(\d+)',
        r'"totalViews"\s*:\s*(\d+)',
        r'"stats"\s*:\s*\{[^}]*"views"\s*:\s*(\d+)',
    ):
        m = re.search(pat, page_html, re.I | re.S)
        if m:
            return safe_int(m.group(1))
    return 0


def format_upload_date(iso_val: str) -> str:
    s = clean_text(iso_val)
    if not s:
        return ""
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}T", s):
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            return f"{d.day:02d} {MONTHS_RU.get(d.month, d.month)} {d.year}"
    except Exception:
        pass
    return s


def resolve_ok_content_id(page_html: str, url: str, final_url: str = "") -> str:
    for candidate in (final_url, url):
        if candidate:
            v = extract_ok_video_id(clean_text(candidate))
            if v:
                return v
    og = extract_meta_property(page_html, "og:url")
    if og:
        v = extract_ok_video_id(og)
        if v:
            return v
    return extract_meta_property(page_html, "ya:ovs:content_id") or ""


def parse_ok_video_html(page_html: str, url: str, final_url: str = "") -> dict:
    video_id = resolve_ok_content_id(page_html, url, final_url=final_url)
    views = safe_int(extract_meta_property(page_html, "ya:ovs:views_total"))
    if views == 0:
        views = views_from_embedded_json(page_html)
    if views == 0:
        views = views_from_visible_html(page_html)

    author = extract_meta_property(page_html, "ya:ovs:login")
    title = extract_meta_property(page_html, "og:title") or extract_meta_property(page_html, "title")
    upload_raw = extract_meta_property(page_html, "ya:ovs:upload_date")
    publish = format_upload_date(upload_raw)
    owner_url = extract_profile_url(page_html)
    owner_id = extract_profile_id(page_html) or ""

    status = "ok"
    tl = (title or "").lower()
    if "не найден" in tl or "not found" in tl or "удалён" in tl or "удален" in tl:
        status = "unavailable"

    oid = owner_id or author or ""
    return make_ok_item(
        url=url,
        video_id=video_id or "",
        owner_id=str(oid),
        owner_name=author or "Unknown",
        owner_url=owner_url,
        owner_avatar="",
        views=views,
        likes=safe_int(extract_meta_property(page_html, "ya:ovs:likes")),
        comments=safe_int(extract_meta_property(page_html, "ya:ovs:comments")),
        shares=0,
        collects=0,
        publish_display=publish,
        desc=title,
        status=status,
        source_index=0,
    )


def make_ok_item(
    url: str,
    video_id: str,
    owner_id: str,
    owner_name: str,
    owner_url: str,
    owner_avatar: str,
    views: int,
    likes: int,
    comments: int,
    shares: int,
    collects: int,
    publish_display: str,
    desc: str,
    status: str,
    source_index: int = 0,
) -> dict:
    oid = str(owner_id or "").strip()
    return {
        "url": url,
        "raw_id": video_id,
        "video_id": video_id,
        "owner_id": oid,
        "owner_name": owner_name or "Unknown",
        "owner_unique_id": oid,
        "owner_url": owner_url or "",
        "owner_avatar": owner_avatar or "",
        "views": int(views or 0),
        "likes": int(likes or 0),
        "comments": int(comments or 0),
        "shares": int(shares or 0),
        "collects": int(collects or 0),
        "reposts": 0,
        "publish_date": publish_display,
        "date_published_display": publish_display,
        "description": desc or "",
        "parse_status": status,
        "source_index": source_index,
    }


def parse_ok_video_dom(page_html: str, url: str, final_url: str = "") -> dict | None:
    """Разбор блока data-module=VideoLayerPins (как в живом DOM после React)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(page_html, "html.parser")
    root = soup.select_one('[data-module="VideoLayerPins"]')
    if not root:
        return None

    movie_id = (root.get("data-movie-id") or "").strip()
    views = 0
    info_cnt = root.select_one(".vp-layer-info_cnt")
    if info_cnt:
        for block in info_cnt.select(".vp-layer-info_i"):
            txt = clean_text(block.get_text(" ", strip=True))
            if "просмотр" in txt.lower():
                m = re.search(r"(\d+)", txt)
                if m:
                    views = int(m.group(1))
                break

    title_el = root.select_one("h1.vp-layer-info_h") or root.select_one(".vp-layer-info_title h1")
    title = clean_text(title_el.get_text()) if title_el else ""

    date_el = root.select_one(".vp-layer-info_date")
    publish_short = clean_text(date_el.get_text()) if date_el else ""

    owner_name = ""
    owner_id = ""
    owner_url = ""
    owner_avatar = ""
    auth = root.select_one("autoplay-layer-movie-author[data-props]")
    if auth and auth.get("data-props"):
        try:
            raw = auth["data-props"]
            props = json.loads(html_module.unescape(raw))
            owner_name = clean_text(props.get("name")) or ""
            owner_id = str(props.get("id") or "").strip()
            rel = props.get("url") or ""
            if rel.startswith("/"):
                owner_url = "https://ok.ru" + rel.split("?")[0].rstrip("/")
            elif rel.startswith("http"):
                owner_url = rel.split("?")[0].rstrip("/")
            owner_avatar = clean_text(props.get("imgSrc")) or ""
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass

    name_fallback = root.select_one(".autoplay_layer_movie_author_movie-author_name")
    if not owner_name and name_fallback:
        owner_name = clean_text(name_fallback.get_text())

    link_fb = root.select_one('a.autoplay_layer_movie_author_link[href*="/profile/"]')
    if link_fb and not owner_url:
        href = link_fb.get("href") or ""
        if href.startswith("/"):
            owner_url = "https://ok.ru" + href.split("?")[0].rstrip("/")

    likes = 0
    like_el = root.select_one('[data-like-reference-id^="MOVIE:"] .widget_count.js-count')
    if like_el:
        likes = safe_int(like_el.get_text())

    shares = 0
    resh = root.select_one('[data-type="RESHARE"] .widget_count.js-count') or root.select_one(
        '[data-module="LikeComponent"][data-type="RESHARE"] ~ span.widget_count'
    )
    if resh:
        shares = safe_int(resh.get_text())

    comments = safe_int(extract_meta_property(page_html, "ya:ovs:comments"))

    vid = movie_id or extract_video_id(final_url or url) or resolve_ok_content_id(page_html, url, final_url)
    status = "ok"

    return make_ok_item(
        url=url,
        video_id=str(vid),
        owner_id=owner_id,
        owner_name=owner_name or "Unknown",
        owner_url=owner_url,
        owner_avatar=owner_avatar,
        views=views,
        likes=likes,
        comments=comments,
        shares=shares,
        collects=0,
        publish_display=publish_short,
        desc=title,
        status=status,
        source_index=0,
    )


def parse_ok_page(page_html: str, url: str, final_url: str = "") -> dict:
    dom = parse_ok_video_dom(page_html, url, final_url=final_url)
    meta = parse_ok_video_html(page_html, url, final_url=final_url)
    if not dom:
        meta["parse_status"] = meta.get("parse_status") or ("ok_dom_missing" if "VideoLayerPins" not in page_html else "ok")
        return meta

    if dom.get("views", 0) == 0 and meta.get("views", 0):
        dom["views"] = meta["views"]
    if (not dom.get("owner_name") or dom.get("owner_name") == "Unknown") and meta.get("owner_name"):
        dom["owner_name"] = meta["owner_name"]
        if not dom.get("owner_id") and meta.get("owner_id"):
            dom["owner_id"] = meta["owner_id"]
            dom["owner_unique_id"] = str(meta["owner_id"])
    if not dom.get("owner_url") and meta.get("owner_url"):
        dom["owner_url"] = meta["owner_url"]
    if dom.get("comments", 0) == 0 and meta.get("comments", 0):
        dom["comments"] = meta["comments"]
    if not dom.get("description") and meta.get("description"):
        dom["description"] = meta["description"]
    if not dom.get("date_published_display") and meta.get("date_published_display"):
        dom["date_published_display"] = meta["date_published_display"]
        dom["publish_date"] = meta["publish_date"]

    dom["parse_status"] = "ok"
    return dom


def fetch_html_requests(
    url: str,
    session: requests.Session,
    timeout: float = 45.0,
) -> tuple[str, int, str]:
    r = session.get(url, timeout=timeout, allow_redirects=True)
    if r.encoding is None or r.encoding.lower() in ("iso-8859-1", "ascii"):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text, r.status_code, str(r.url)


def ok_cookies_playwright(cookie_header: str) -> list[dict]:
    out: list[dict] = []
    for part in cookie_header.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "value": value,
                "domain": ".ok.ru",
                "path": "/",
            }
        )
    return out


def fetch_html_playwright(
    url: str,
    cookie_header: str,
    headless: bool,
    wait_ms: int,
    verbose: bool,
) -> tuple[str, int, str]:
    from playwright.sync_api import sync_playwright

    log(f"[OK PW] {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            extra_http_headers={
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
            },
        )
        if cookie_header:
            try:
                context.add_cookies(ok_cookies_playwright(cookie_header))
            except Exception as exc:
                if verbose:
                    log(f"[OK PW] cookies: {exc}")

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        try:
            page.wait_for_selector('[data-module="VideoLayerPins"]', timeout=wait_ms)
        except Exception as exc:
            if verbose:
                log(f"[OK PW] VideoLayerPins wait: {exc}")
        # Даём дорисоваться виджетам
        page.wait_for_timeout(800)
        html_out = page.content()
        final_url = str(page.url)
        page.close()
        context.close()
        browser.close()

    return html_out, 200, final_url


def build_owner_summary(items: list[dict]) -> list[dict]:
    owners: dict[str, dict] = {}

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


def build_owner_rows(items: list[dict]) -> str:
    rows = []

    for owner in build_owner_summary(items):
        avg_views = round(owner["views_sum"] / owner["videos_count"]) if owner["videos_count"] else 0

        avatar = ""
        if owner.get("owner_avatar"):
            avatar = f'<img class="owner-avatar" src="{html_module.escape(owner["owner_avatar"], quote=True)}">'

        rows.append(f"""
        <tr>
            <td>
                <div class="owner-cell">
                    {avatar}
                    <div>
                        <a href="{html_module.escape(owner.get("owner_url") or "", quote=True)}" target="_blank">
                            <strong>{html_module.escape(owner.get("owner_name") or "")}</strong>
                        </a>
                        <div class="muted">id {html_module.escape(str(owner.get("owner_unique_id") or ""))}</div>
                        <div class="muted">ID {html_module.escape(str(owner.get("owner_id") or ""))}</div>
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


def build_video_rows(items: list[dict]) -> str:
    rows = []

    for idx, item in enumerate(items, start=1):
        avatar = ""
        if item.get("owner_avatar"):
            avatar = f'<img class="owner-avatar" src="{html_module.escape(item["owner_avatar"], quote=True)}">'

        search = html_module.escape(
            f'{item.get("description","")} {item.get("owner_name","")} {item.get("owner_unique_id","")} {item.get("video_id","")} {item.get("url","")}'.lower(),
            quote=True,
        )

        rows.append(f"""
        <tr class="data-row" data-search="{search}" data-views="{safe_int(item.get("views"))}" data-manually-hidden="0">
            <td><input type="checkbox" class="row-check"></td>
            <td>{idx}</td>
            <td>{html_module.escape(item.get("date_published_display") or item.get("publish_date") or "")}</td>
            <td>{safe_int(item.get("views"))}</td>
            <td>
                <div class="owner-cell">
                    {avatar}
                    <div>
                        <a href="{html_module.escape(item.get("owner_url") or "", quote=True)}" target="_blank">
                            <strong>{html_module.escape(item.get("owner_name") or "")}</strong>
                        </a>
                        <div class="muted">id {html_module.escape(str(item.get("owner_unique_id") or ""))}</div>
                        <div class="muted">status: {html_module.escape(item.get("parse_status") or "")}</div>
                    </div>
                </div>
            </td>
            <td><a href="{html_module.escape(item.get("url") or "", quote=True)}" target="_blank">{html_module.escape(item.get("url") or "")}</a></td>
            <td>{html_module.escape(item.get("video_id") or "")}</td>
            <td>{safe_int(item.get("likes"))}</td>
            <td>{safe_int(item.get("comments"))}</td>
            <td>{safe_int(item.get("shares"))}</td>
            <td>{safe_int(item.get("collects"))}</td>
            <td class="description-cell">{html_module.escape(item.get("description") or "")}</td>
        </tr>
        """)

    return "\n".join(rows)


def render_html_grouped(items: list[dict], title: str) -> str:
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
<title>{html_module.escape(title)}</title>
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
<h1>{html_module.escape(title)}</h1>
<p><a href="{html_module.escape(restart_url, quote=True)}" style="display:inline-block;padding:8px 12px;border:1px solid #c7d2e0;border-radius:10px;background:#eef3f8;color:#1f2937;text-decoration:none;font-weight:600;">Парсить заново</a></p>

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


def main() -> None:
    parser = argparse.ArgumentParser(description="OK.ru — метрики видео (Playwright + VideoLayerPins), отчёт как TikTok")
    parser.add_argument("--input", default="ok.txt")
    parser.add_argument("--output", default="ok_index.html")
    parser.add_argument("--title", default="Одноклассники — видео")
    parser.add_argument("--save-json", default="")
    parser.add_argument("--cookie", default="")
    parser.add_argument("--cookie-file", default="ok_token.txt")
    parser.add_argument("--pause", type=float, default=0.35)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--no-playwright",
        action="store_true",
        help="Только requests (без браузера)",
    )
    parser.add_argument("--headless", action="store_true", default=True, help="Playwright headless (по умолчанию да)")
    parser.add_argument("--no-headless", action="store_true", help="Показать окно Chromium")
    parser.add_argument("--playwright-wait-ms", type=int, default=25000, help="Ожидание селектора VideoLayerPins")
    args = parser.parse_args()

    headless = not args.no_headless

    cookie_header = clean_text(args.cookie)
    if not cookie_header and args.cookie_file and Path(args.cookie_file).exists():
        cookie_header = Path(args.cookie_file).read_text(encoding="utf-8").strip()
    if not cookie_header:
        cookie_header = os.environ.get("OK_COOKIE", "").strip()

    urls = load_urls(args.input)
    if not urls:
        raise RuntimeError(f"Нет ссылок OK.ru в файле: {args.input}")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://ok.ru/",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    if cookie_header:
        session.headers["Cookie"] = cookie_header

    use_pw = not args.no_playwright
    if use_pw:
        try:
            import playwright  # noqa: F401
        except ImportError:
            log("WARN: playwright не установлен, fallback на requests")
            use_pw = False

    items: list[dict] = []
    n = len(urls)
    for i, url in enumerate(urls, start=1):
        print(f"Fetching {i} / {n}", flush=True)
        try:
            if use_pw:
                try:
                    page_html, code, final_url = fetch_html_playwright(
                        url, cookie_header, headless=headless, wait_ms=args.playwright_wait_ms, verbose=args.verbose
                    )
                except Exception as exc:
                    log(f"[OK PW] fallback requests: {exc}")
                    page_html, code, final_url = fetch_html_requests(url, session)
            else:
                page_html, code, final_url = fetch_html_requests(url, session)

            if args.verbose:
                log(f"GET {code} final={final_url[:80]}...")

            if not (200 <= code < 300):
                items.append(
                    make_ok_item(
                        url,
                        extract_video_id(url),
                        "",
                        "Unknown",
                        "",
                        "",
                        0,
                        0,
                        0,
                        0,
                        0,
                        "",
                        "",
                        f"http_{code}",
                        source_index=i,
                    )
                )
            else:
                item = parse_ok_page(page_html, url, final_url=final_url)
                item["source_index"] = i
                items.append(item)
        except Exception as exc:
            log(f"ERROR {url}: {exc}")
            items.append(
                make_ok_item(
                    url,
                    extract_video_id(url),
                    "",
                    "Unknown",
                    "",
                    "",
                    0,
                    0,
                    0,
                    0,
                    0,
                    "",
                    "",
                    "error",
                    source_index=i,
                )
            )
        if args.pause > 0 and i < n:
            time.sleep(args.pause)

    Path(args.output).write_text(render_html_grouped(items, args.title), encoding="utf-8")
    if args.save_json:
        Path(args.save_json).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"HTML saved to {args.output}", flush=True)


if __name__ == "__main__":
    main()
