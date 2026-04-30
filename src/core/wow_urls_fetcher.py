#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

import requests


DEFAULT_BASE_URL = "https://core.wowblogger.ru/api/content-factory/campaigns/{campaign_id}/slots/"


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def read_key_value_file(path):
    """
    wowData.txt, пример:

    campaign_id=27619
    bloggers=87255
    date_from=2026-04-17
    date_to=2026-05-16
    bearerToken=272091|a5hNcMMV0CQaKed863ctpSVnuJwlpzy5DaUde65J

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
    """
    if value is None:
        return []

    text = str(value).strip()

    if not text:
        return []

    return re.findall(r"\d+", text)


def make_headers(token):
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


def build_url(base_url, campaign_id, bloggers, date_from, date_to):
    url = base_url.format(campaign_id=campaign_id).rstrip("/") + "/"

    params = []

    for blogger_id in bloggers:
        params.append(("bloggers[]", blogger_id))

    if date_from:
        params.append(("date_from", date_from))

    if date_to:
        params.append(("date_to", date_to))

    return url + "?" + urlencode(params)


def extract_post_urls(response_json):
    urls = []

    for day_item in response_json.get("data", []):
        if not isinstance(day_item, dict):
            continue

        placements = day_item.get("placements", [])

        if not isinstance(placements, list):
            continue

        for placement in placements:
            if not isinstance(placement, dict):
                continue

            post_url = placement.get("post_url")

            if not post_url:
                continue

            # В ответе бывают строки типа "https://vk.ru/clip... VK"
            match = re.search(r"https?://[^\s'\"<>]+", str(post_url))

            if match:
                urls.append(match.group(0).strip())

    return unique_keep_order(urls)


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


def main():
    parser = argparse.ArgumentParser(description="Fetch WOWBlogger Content Factory placement post_url values into urls.txt")
    parser.add_argument("--config", default="wowData.txt", help="Файл с campaign_id/bloggers/date_from/date_to/bearerToken")
    parser.add_argument("--output", default="urls.txt", help="Куда сохранить список ссылок")
    parser.add_argument("--save-json", default="", help="Сохранить полный API response JSON")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)

    # Можно переопределить параметры из CLI, если нужно.
    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--bloggers", default="")
    parser.add_argument("--date-from", default="")
    parser.add_argument("--date-to", default="")
    parser.add_argument("--bearer-token", default="")
    parser.add_argument("--verbose", action="store_true")

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

    bloggers = parse_bloggers(bloggers_raw)

    if not campaign_id:
        raise RuntimeError("Не задан campaign_id в wowData.txt или --campaign-id")

    if not bloggers:
        raise RuntimeError("Не задан bloggers в wowData.txt или --bloggers")

    if not date_from:
        raise RuntimeError("Не задан date_from в wowData.txt или --date-from")

    if not date_to:
        raise RuntimeError("Не задан date_to в wowData.txt или --date-to")

    if not token:
        raise RuntimeError("Не задан bearerToken в wowData.txt или --bearer-token")

    all_urls = []
    all_responses = {}

    for blogger_id in bloggers:
        url = build_url(args.base_url, campaign_id, [blogger_id], date_from, date_to)

        if args.verbose:
            log(f"[GET] blogger={blogger_id} | {url}")

        response = requests.get(
            url,
            headers=make_headers(token),
            timeout=60,
        )

        if args.verbose:
            log(f"[STATUS] blogger={blogger_id} | {response.status_code}")

        response.raise_for_status()

        response_json = response.json()
        all_responses[str(blogger_id)] = response_json

        urls = extract_post_urls(response_json)
        all_urls.extend(urls)

        if args.verbose:
            log(f"[URLS] blogger={blogger_id} | {len(urls)}")

    all_urls = unique_keep_order(all_urls)

    if args.save_json:
        Path(args.save_json).write_text(json.dumps(all_responses, ensure_ascii=False, indent=2), encoding="utf-8")

    write_lines(args.output, all_urls)

    print(f"Готово: {len(all_urls)} ссылок сохранено в {args.output}")
    print(f"Блогеров обработано: {len(bloggers)}")


if __name__ == "__main__":
    main()
