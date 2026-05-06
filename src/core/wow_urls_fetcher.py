#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

from src.core import wow_api_client
from src.core.urls_splitter import normalize_url


DEFAULT_BASE_URL = "https://core.wowblogger.ru/api/content-factory/campaigns/{campaign_id}/slots/"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def read_key_value_file(path):
    """
    wowData.txt, пример:

    campaign_id=27619
    bloggers=87255
    bloggers=all
    date_from=2026-04-17
    date_to=2026-05-16
    bearerToken=272091|...
    skip_weeks=1,3
    include_profile_urls=0
    weekly_report=1

    Также поддерживает bearer_token / token.
    """
    data = {}

    if not path:
        return data

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(f"Не найден файл: {path}")

    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()

    return data


def first_non_empty(*values):
    for value in values:
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def parse_bloggers(value):
    """
    Поддерживает:
      87255
      87255,12345
      87255 12345
      [87255,12345]
      all
    """
    if value is None:
        return []

    text = str(value).strip().lower()
    if text in ("all", "*", "every"):
        return ["__ALL__"]

    if not text:
        return []

    return re.findall(r"\d+", str(value))


def parse_skip_weeks(val: str) -> list[int]:
    if not val or not str(val).strip():
        return []
    out: list[int] = []
    for part in re.split(r"[,\s;]+", str(val)):
        part = part.strip()
        if part.isdigit():
            n = int(part)
            if n >= 1:
                out.append(n)
    return sorted(set(out))


def unique_keep_order(items):
    seen = set()
    result = []

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


def write_lines(path, lines):
    Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def normalize_platform_type(value: str) -> str:
    v = (value or "").strip().lower()
    mapping = {
        "zen": "dzen",
        "odnoklassniki": "ok",
        "odnoklassniki_ru": "ok",
        "ok_ru": "ok",
        "youtube_shorts": "youtube",
    }
    return mapping.get(v, v)


def platform_from_url(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ""
    host = host.replace("www.", "")
    if host in ("vk.com", "vk.ru", "m.vk.com", "m.vk.ru"):
        return "vk"
    if host in ("tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"):
        return "tiktok"
    if host in ("youtube.com", "m.youtube.com", "youtu.be"):
        return "youtube"
    if host in ("dzen.ru", "m.dzen.ru", "zen.yandex.ru", "m.zen.yandex.ru"):
        return "dzen"
    if host in ("pinterest.com", "ru.pinterest.com", "m.pinterest.com", "pin.it"):
        return "pinterest"
    if host in ("ok.ru", "m.ok.ru"):
        return "ok"
    return ""


def build_slots_validation(entries: list[dict]) -> dict:
    dup_map: dict[str, list[dict]] = {}
    for e in entries:
        u = e.get("url") or ""
        if not u:
            continue
        key = normalize_url(u)
        dup_map.setdefault(key, []).append(e)
    duplicates = []
    for key, arr in dup_map.items():
        if len(arr) < 2:
            continue
        duplicates.append(
            {
                "url_normalized": key,
                "count": len(arr),
                "samples": [x.get("url") or "" for x in arr[:5]],
                "blogger_ids": sorted({str(x.get("blogger_user_id") or "") for x in arr if x.get("blogger_user_id") is not None}),
            }
        )

    mismatches = []
    for e in entries:
        expected = normalize_platform_type(str(e.get("platform_type") or ""))
        if not expected:
            continue
        actual = platform_from_url(str(e.get("url") or ""))
        if not actual:
            continue
        if expected != actual:
            mismatches.append(
                {
                    "url": e.get("url") or "",
                    "expected_platform": expected,
                    "actual_platform": actual,
                    "blogger_user_id": e.get("blogger_user_id"),
                    "scenario_id": e.get("scenario_id"),
                    "slot_date": e.get("slot_date") or "",
                }
            )
    return {
        "duplicates_count": len(duplicates),
        "platform_mismatches_count": len(mismatches),
        "duplicates": sorted(duplicates, key=lambda x: (-int(x.get("count") or 0), x.get("url_normalized") or "")),
        "platform_mismatches": mismatches,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch WOWBlogger Content Factory URLs into urls.txt")
    parser.add_argument("--config", default="wowData.txt", help="Файл с campaign_id/bloggers/date_from/date_to/bearerToken")
    parser.add_argument("--output", default="urls.txt", help="Куда сохранить список ссылок")
    parser.add_argument("--save-json", default="", help="Сохранить полный API response JSON (slots по блогерам)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)

    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--bloggers", default="")
    parser.add_argument("--date-from", default="")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--bearer-token", default="")
    parser.add_argument("--verbose", action="store_true")

    parser.add_argument(
        "--slots-meta-output",
        default="wow_slots_meta.json",
        help="JSON со слотами: url, slot_date, scenario_id, blogger_user_id",
    )
    parser.add_argument(
        "--campaign-context-output",
        default="wow_campaign_context.json",
        help="JSON: сценарии, период, skip_weeks, метаданные кампании",
    )
    parser.add_argument(
        "--validation-output",
        default="wow_slots_validation.json",
        help="JSON: дубли и несоответствие platform_type/url",
    )
    parser.add_argument(
        "--no-slots-meta",
        action="store_true",
        help="Не писать wow_slots_meta.json",
    )
    parser.add_argument(
        "--include-profile-urls",
        action="store_true",
        help="Добавить URL профилей из ответа bloggers (дополнительно к слотам)",
    )

    args = parser.parse_args()

    config = read_key_value_file(args.config)

    campaign_id = first_non_empty(
        args.campaign_id,
        config.get("campaign_id"),
        config.get("campaignId"),
        config.get("campaign"),
    )

    bloggers_raw = first_non_empty(
        args.bloggers,
        config.get("bloggers"),
        config.get("blogger_id"),
        config.get("bloggerId"),
    )

    date_from = first_non_empty(args.date_from, config.get("date_from"), config.get("dateFrom"))
    date_to = first_non_empty(args.date_to, config.get("date_to"), config.get("dateTo"))

    token = first_non_empty(
        args.bearer_token,
        config.get("bearerToken"),
        config.get("bearer_token"),
        config.get("token"),
    )

    skip_weeks = parse_skip_weeks(first_non_empty(config.get("skip_weeks"), config.get("skipWeeks"), ""))

    include_profiles = args.include_profile_urls or config.get("include_profile_urls", "").lower() in (
        "1",
        "true",
        "yes",
    )

    weekly_report_flag = config.get("weekly_report", "").lower() in ("1", "true", "yes")

    blogger_tokens = parse_bloggers(bloggers_raw)

    if not campaign_id:
        raise RuntimeError("Не задан campaign_id в wowData.txt или --campaign-id")

    if not date_from:
        raise RuntimeError("Не задан date_from в wowData.txt или --date-from")

    if not date_to:
        raise RuntimeError("Не задан date_to в wowData.txt или --date-to")

    if not token:
        raise RuntimeError("Не задан bearerToken в wowData.txt или --bearer-token")

    bloggers_payload = wow_api_client.fetch_campaign_bloggers(campaign_id, token)
    scenarios_payload = wow_api_client.fetch_campaign_scenarios(campaign_id, token)
    campaign_detail = wow_api_client.fetch_campaign_detail(campaign_id, token)

    all_user_ids = []
    for b in bloggers_payload:
        uid = b.get("user_id")
        if uid is not None:
            all_user_ids.append(str(int(uid)))

    if blogger_tokens and blogger_tokens[0] == "__ALL__":
        bloggers = all_user_ids
    elif blogger_tokens:
        bloggers = blogger_tokens
    elif all_user_ids:
        bloggers = all_user_ids
    else:
        raise RuntimeError("Не задан bloggers в wowData.txt (или bloggers=all), и API не вернул блогеров")

    if not bloggers:
        raise RuntimeError("Список блогеров пуст после разрешения bloggers=all")

    all_urls: list[str] = []
    all_enriched: list[dict] = []
    all_responses: dict = {}

    for blogger_id_str in bloggers:
        blogger_id = int(blogger_id_str)
        url = wow_api_client.build_slots_url(campaign_id, [blogger_id_str], date_from, date_to)

        if args.verbose:
            log(f"[GET] blogger={blogger_id_str} | {url}")

        response = requests.get(
            url,
            headers=wow_api_client.make_headers(token),
            timeout=60,
        )

        if args.verbose:
            log(f"[STATUS] blogger={blogger_id_str} | {response.status_code}")

        response.raise_for_status()

        response_json = response.json()
        all_responses[str(blogger_id_str)] = response_json

        enriched = wow_api_client.extract_enriched_slots(response_json, blogger_id)
        all_enriched.extend(enriched)

        for e in enriched:
            all_urls.append(e["url"])

        if args.verbose:
            log(f"[URLS] blogger={blogger_id_str} | {len(enriched)}")

    all_urls = unique_keep_order(all_urls)

    profile_urls: list[str] = []
    if include_profiles:
        profile_urls = wow_api_client.collect_profile_urls_from_bloggers(bloggers_payload)
        for u in profile_urls:
            if u not in all_urls:
                all_urls.append(u)

    if args.save_json:
        Path(args.save_json).write_text(json.dumps(all_responses, ensure_ascii=False, indent=2), encoding="utf-8")

    write_lines(args.output, all_urls)
    validation = build_slots_validation(all_enriched)

    context = {
        "campaign_id": campaign_id,
        "date_from": date_from,
        "date_to": date_to,
        "skip_weeks": skip_weeks,
        "weekly_report": weekly_report_flag,
        "scenarios": scenarios_payload,
        "bloggers_count": len(bloggers_payload),
        "slots_entries_count": len(all_enriched),
        "slots_validation": validation,
        "campaign_detail": campaign_detail,
    }

    Path(args.campaign_context_output).write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.no_slots_meta:
        Path(args.slots_meta_output).write_text(
            json.dumps({"entries": all_enriched}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    Path(args.validation_output).write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Готово: {len(all_urls)} ссылок сохранено в {args.output}")
    print(f"Блогеров обработано (слоты): {len(bloggers)}")
    if include_profiles and profile_urls:
        print(f"Добавлено профильных URL: {len(profile_urls)}")
    print(f"Контекст кампании: {args.campaign_context_output}")
    print(
        f"Валидация слотов: {args.validation_output} "
        f"(дубли: {validation['duplicates_count']}, mismatch platform: {validation['platform_mismatches_count']})"
    )
    if not args.no_slots_meta:
        print(f"Мета слотов: {args.slots_meta_output} ({len(all_enriched)} записей)")


if __name__ == "__main__":
    main()
