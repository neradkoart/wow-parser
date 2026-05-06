#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HTTP-клиент WOW Content Factory: блогеры, сценарии, слоты, построение URL профилей.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import requests

BASE_CORE = "https://core.wowblogger.ru"


def make_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "*/*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7,uk;q=0.6",
        "Cache-Control": "no-cache",
        "Origin": "https://factory.wowblogger.ru",
        "Pragma": "no-cache",
        "Referer": "https://factory.wowblogger.ru/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def fetch_campaign_bloggers(campaign_id: str, token: str, timeout: int = 60) -> list[dict[str, Any]]:
    url = f"{BASE_CORE}/api/content-factory/campaigns/{campaign_id}/bloggers?search"
    r = requests.get(url, headers=make_headers(token), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    bloggers = data.get("bloggers")
    if not isinstance(bloggers, list):
        return []
    return [x for x in bloggers if isinstance(x, dict)]


def fetch_campaign_scenarios(campaign_id: str, token: str, timeout: int = 60) -> list[dict[str, Any]]:
    url = f"{BASE_CORE}/api/content-factory/campaigns/{campaign_id}/scenarios"
    r = requests.get(url, headers=make_headers(token), timeout=timeout)
    r.raise_for_status()
    data = r.json()
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list):
        return []
    return [x for x in scenarios if isinstance(x, dict)]


def fetch_campaign_detail(campaign_id: str, token: str, timeout: int = 60) -> dict[str, Any] | None:
    url = f"{BASE_CORE}/api/content-factory/campaigns/{campaign_id}"
    r = requests.get(url, headers=make_headers(token), timeout=timeout)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else None


def build_slots_url(campaign_id: str, bloggers: list[str], date_from: str, date_to: str) -> str:
    base = f"{BASE_CORE}/api/content-factory/campaigns/{campaign_id}/slots/".rstrip("/") + "/"
    params: list[tuple[str, str]] = []
    for blogger_id in bloggers:
        params.append(("bloggers[]", blogger_id))
    if date_from:
        params.append(("date_from", date_from))
    if date_to:
        params.append(("date_to", date_to))
    return base + "?" + urlencode(params)


def pick_scenario_id(placement: dict[str, Any]) -> int | None:
    for key in (
        "scenario_id",
        "content_scenario_id",
        "factory_scenario_id",
        "wow_scenario_id",
        "content_factory_scenario_id",
    ):
        v = placement.get(key)
        if v is None:
            continue
        if isinstance(v, dict):
            v = v.get("id") or v.get("scenario_id")
        try:
            if v is not None and str(v).strip().lstrip("-").isdigit():
                return int(v)
        except (TypeError, ValueError):
            continue
    nested = placement.get("scenario")
    if isinstance(nested, dict):
        sid = nested.get("id") or nested.get("scenario_id")
        if sid is not None and str(sid).strip().lstrip("-").isdigit():
            return int(sid)
    return None


def day_item_calendar_date(day_item: dict[str, Any]) -> str:
    for key in ("date", "day", "calendar_date", "slot_date", "published_at"):
        v = day_item.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        if "T" in s:
            return s.split("T", 1)[0]
        return s[:10]
    return ""


def extract_post_url_raw(post_field: Any) -> str:
    if not post_field:
        return ""
    match = re.search(r"https?://[^\s'\"<>]+", str(post_field))
    return match.group(0).strip() if match else ""


def extract_enriched_slots(response_json: dict[str, Any], blogger_user_id: int | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    data = response_json.get("data")
    if not isinstance(data, list):
        return out

    for day_item in data:
        if not isinstance(day_item, dict):
            continue
        cal_date = day_item_calendar_date(day_item)
        placements = day_item.get("placements")
        if not isinstance(placements, list):
            continue
        for placement in placements:
            if not isinstance(placement, dict):
                continue
            raw_url = placement.get("post_url") or placement.get("url") or placement.get("link")
            url = extract_post_url_raw(raw_url)
            if not url:
                continue
            scenario_id = pick_scenario_id(placement)
            social = placement.get("social") if isinstance(placement.get("social"), dict) else {}
            platform_type = (
                placement.get("platform_type")
                or social.get("platform_type")
                or social.get("type")
                or ""
            )
            out.append(
                {
                    "url": url,
                    "slot_date": cal_date,
                    "scenario_id": scenario_id,
                    "blogger_user_id": blogger_user_id,
                    "platform_type": str(platform_type or "").strip().lower(),
                    "placement_keys": sorted(placement.keys()),
                }
            )
    return out


_RE_HANDLE = re.compile(r"^[\w.@\-]{2,256}$", re.UNICODE)


def social_display_to_profile_url(platform_type: str, name: str) -> str | None:
    """
    Строит URL профиля/канала для парсеров. Если name уже URL — возвращает как есть (с https).
    """
    name = (name or "").strip()
    if not name:
        return None
    if name.startswith("http://") or name.startswith("https://"):
        return name
    pt = (platform_type or "").strip().lower()
    if pt == "youtube":
        if name.startswith("@"):
            return f"https://www.youtube.com/{name}"
        if "/" not in name and " " not in name:
            return f"https://www.youtube.com/@{name.lstrip('@')}"
        return None
    if pt == "tiktok":
        h = name.lstrip("@")
        if _RE_HANDLE.match(h):
            return f"https://www.tiktok.com/@{h}"
        return None
    if pt in ("zen", "dzen"):
        if "dzen.ru" in name or "zen.yandex" in name:
            return "https://" + name.split("://", 1)[-1] if "://" in name else name
        if name.startswith("id/") or "/id/" in name:
            path = name if name.startswith("http") else f"https://dzen.ru/{name.lstrip('/')}"
            return path
        return f"https://dzen.ru/{quote(name)}"
    if pt == "vk":
        if name.startswith("club") or name.startswith("public") or name.startswith("id"):
            return f"https://vk.ru/{name}"
        if re.match(r"^[\w._-]+$", name):
            return f"https://vk.ru/{name}"
        return None
    if pt == "instagram":
        h = name.lstrip("@")
        return f"https://www.instagram.com/{h}/" if _RE_HANDLE.match(h) else None
    if pt == "pinterest":
        return f"https://www.pinterest.com/{name.lstrip('@')}/" if _RE_HANDLE.match(name.lstrip("@")) else None
    if pt in ("ok", "odnoklassniki", "odnoklassniki_ru", "ok_ru"):
        low = name.lower()
        if "ok.ru" in low or "odnoklassniki.ru" in low or "m.ok.ru" in low:
            u = name if name.startswith("http") else f"https://{name.lstrip('/')}"
            try:
                p = urlparse(u)
                if p.netloc:
                    return u.split("?", 1)[0].rstrip("/")
            except Exception:
                pass
            return None
        n = name.strip()
        if n.isdigit():
            return f"https://ok.ru/profile/{n}"
        if re.match(r"^id\d+$", n, re.I):
            return f"https://ok.ru/profile/{n[2:]}"
        h = n.lstrip("@")
        if _RE_HANDLE.match(h):
            return f"https://ok.ru/{h}"
        return None
    return None


def collect_profile_urls_from_bloggers(bloggers_payload: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for blogger in bloggers_payload:
        socials = blogger.get("socials")
        if not isinstance(socials, list):
            continue
        for soc in socials:
            if not isinstance(soc, dict):
                continue
            pt = str(soc.get("platform_type") or "")
            nm = str(soc.get("name") or "")
            u = social_display_to_profile_url(pt, nm)
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
    return urls
