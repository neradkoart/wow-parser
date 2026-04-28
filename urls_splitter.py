#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import requests


URL_RE = re.compile(r"https?://[^\s'\"<>]+")


def clean_url(raw):
    return raw.strip().strip("'\"").rstrip(".,);]}")


def extract_vk_clip_raw_id(url):
    parsed = urlparse(url)

    match = re.search(r"(?:^|[?&])z=clip(-?\d+_\d+)", parsed.query)
    if match:
        return match.group(1)

    match = re.search(r"/clip(-?\d+_\d+)", parsed.path)
    if match:
        return match.group(1)

    match = re.search(r"clip(-?\d+_\d+)", url)
    if match:
        return match.group(1)

    return ""


def extract_vk_wall_raw_id(url):
    parsed = urlparse(url)

    match = re.search(r"/wall(-?\d+_\d+)", parsed.path)
    if match:
        return match.group(1)

    match = re.search(r"wall(-?\d+_\d+)", url)
    if match:
        return match.group(1)

    return ""


def normalize_url(url):
    url = clean_url(url)
    parsed = urlparse(url)

    if not parsed.scheme or not parsed.netloc:
        return url

    host = parsed.netloc.lower().replace("www.", "")

    # YouTube Shorts
    if host in ("youtube.com", "m.youtube.com", "youtu.be"):
        if host == "youtu.be":
            video_id = parsed.path.strip("/")
            if video_id:
                return f"https://www.youtube.com/shorts/{video_id}"

        if "/shorts/" in parsed.path:
            video_id = parsed.path.split("/shorts/", 1)[1].split("/")[0]
            return f"https://www.youtube.com/shorts/{video_id}"

        if parsed.path == "/watch" and parsed.query:
            match = re.search(r"(?:^|&)v=([^&]+)", parsed.query)
            if match:
                return f"https://www.youtube.com/shorts/{match.group(1)}"

    # TikTok
    if host in ("tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"):
        if host in ("vm.tiktok.com", "vt.tiktok.com"):
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

        match = re.search(r"/@([^/]+)/video/(\d+)", parsed.path)
        if match:
            return f"https://www.tiktok.com/@{match.group(1)}/video/{match.group(2)}"

        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    # Dzen
    if host in ("dzen.ru", "m.dzen.ru", "zen.yandex.ru", "m.zen.yandex.ru"):
        match = re.search(r"/shorts/([^/?#]+)", parsed.path)
        if match:
            return f"https://dzen.ru/shorts/{match.group(1)}"

        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))

    # VK clips / wall
    if host in ("vk.com", "vk.ru", "m.vk.com", "m.vk.ru"):
        clip_raw_id = extract_vk_clip_raw_id(url)
        if clip_raw_id:
            return f"https://vk.ru/clip{clip_raw_id}"

        wall_raw_id = extract_vk_wall_raw_id(url)
        if wall_raw_id:
            return f"https://vk.ru/wall{wall_raw_id}"

    return url


def classify(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")

    if host in ("youtube.com", "m.youtube.com", "youtu.be") or ("youtube" in host and "/shorts/" in parsed.path):
        return "youtube"

    if host in ("tiktok.com", "m.tiktok.com", "vm.tiktok.com", "vt.tiktok.com"):
        return "tiktok"

    if host in ("dzen.ru", "m.dzen.ru", "zen.yandex.ru", "m.zen.yandex.ru") and "/shorts/" in parsed.path:
        return "dzen"

    if host in ("vk.com", "vk.ru", "m.vk.com", "m.vk.ru"):
        if extract_vk_clip_raw_id(url):
            return "vk_clip"

        if extract_vk_wall_raw_id(url):
            return "vk_wall"

        if "clips" in url:
            return "vk"

    return "unknown"


def extract_urls(text):
    urls = []

    for match in URL_RE.finditer(text):
        urls.append(clean_url(match.group(0)))

    bare_pattern = (
        r"(?:^|[\s'\"<>])"
        r"((?:vk\.ru|vk\.com|m\.vk\.ru|m\.vk\.com|"
        r"dzen\.ru|m\.dzen\.ru|zen\.yandex\.ru|m\.zen\.yandex\.ru|"
        r"youtube\.com|m\.youtube\.com|youtu\.be|"
        r"tiktok\.com|m\.tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com)/[^\s'\"<>]+)"
    )

    for match in re.finditer(bare_pattern, text):
        urls.append("https://" + clean_url(match.group(1)))

    return urls


def unique_keep_order(items):
    seen = set()
    result = []

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


def find_duplicates(items):
    counts = {}
    first_index = {}

    for index, item in enumerate(items, start=1):
        counts[item] = counts.get(item, 0) + 1
        first_index.setdefault(item, index)

    duplicates = []
    for item, count in counts.items():
        if count > 1:
            duplicates.append({
                "value": item,
                "count": count,
                "first_index": first_index[item],
            })

    return sorted(duplicates, key=lambda x: x["first_index"])


def build_normalized_duplicate_report(raw_urls):
    normalized_map = {}

    for index, raw_url in enumerate(raw_urls, start=1):
        normalized = normalize_url(raw_url)

        if normalized not in normalized_map:
            normalized_map[normalized] = {
                "normalized_url": normalized,
                "count": 0,
                "items": [],
            }

        normalized_map[normalized]["count"] += 1
        normalized_map[normalized]["items"].append({
            "index": index,
            "raw_url": raw_url,
        })

    duplicates = [item for item in normalized_map.values() if item["count"] > 1]
    return sorted(duplicates, key=lambda x: x["items"][0]["index"])


def write_lines(path, lines):
    Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def load_token(token, token_file):
    if token:
        return token.strip()

    if token_file and Path(token_file).exists():
        return Path(token_file).read_text(encoding="utf-8").strip()

    return ""


def vk_api_call(method, params, token, api_version="5.275", session=None):
    if not token:
        raise RuntimeError("VK token is required")

    session = session or requests.Session()
    payload = dict(params)
    payload["access_token"] = token
    payload["v"] = api_version

    response = session.post(f"https://api.vk.ru/method/{method}", data=payload, timeout=40)
    response.raise_for_status()

    data = response.json()

    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], ensure_ascii=False))

    return data.get("response")


def recursively_find_clip_ids(obj):
    found = []

    if isinstance(obj, dict):
        obj_type = obj.get("type")

        for key in ("clip", "short_video", "video"):
            nested = obj.get(key)

            if isinstance(nested, dict):
                owner_id = nested.get("owner_id") or nested.get("ownerId") or nested.get("owner")
                video_id = nested.get("id") or nested.get("video_id") or nested.get("videoId")

                if owner_id is not None and video_id is not None:
                    raw_id = f"{owner_id}_{video_id}"

                    if obj_type in ("clip", "short_video", "video") or key in ("clip", "short_video", "video"):
                        found.append(raw_id)

        for value in obj.values():
            if isinstance(value, str):
                for match in re.finditer(r"clip(-?\d+_\d+)", value):
                    found.append(match.group(1))
            elif isinstance(value, (dict, list)):
                found.extend(recursively_find_clip_ids(value))

    elif isinstance(obj, list):
        for item in obj:
            found.extend(recursively_find_clip_ids(item))

    return unique_keep_order(found)


def resolve_vk_wall_to_clips(wall_urls, token, api_version="5.275", pause=0.34, verbose=False):
    if not wall_urls or not token:
        return [], wall_urls

    session = requests.Session()
    resolved_clips = []
    unresolved_walls = []
    wall_by_raw_id = {}

    for url in wall_urls:
        raw_id = extract_vk_wall_raw_id(url)
        if raw_id:
            wall_by_raw_id[raw_id] = url
        else:
            unresolved_walls.append(url)

    raw_ids = list(wall_by_raw_id.keys())
    chunk_size = 100

    for start in range(0, len(raw_ids), chunk_size):
        chunk = raw_ids[start:start + chunk_size]

        if verbose:
            print(f"[VK API] wall.getById {start + 1}-{start + len(chunk)} / {len(raw_ids)}")

        try:
            response = vk_api_call(
                "wall.getById",
                {"posts": ",".join(chunk)},
                token=token,
                api_version=api_version,
                session=session,
            )

            posts = response if isinstance(response, list) else response.get("items", []) if isinstance(response, dict) else []
            resolved_raw_ids_in_chunk = set()

            for post in posts:
                post_owner_id = post.get("owner_id")
                post_id = post.get("id")
                post_raw_id = f"{post_owner_id}_{post_id}" if post_owner_id is not None and post_id is not None else ""

                clip_raw_ids = recursively_find_clip_ids(post)

                if clip_raw_ids:
                    resolved_raw_ids_in_chunk.add(post_raw_id)

                    for clip_raw_id in clip_raw_ids:
                        resolved_clips.append(f"https://vk.ru/clip{clip_raw_id}")

                        if verbose:
                            print(f"[VK API] wall{post_raw_id} -> clip{clip_raw_id}")

            for raw_id in chunk:
                if raw_id not in resolved_raw_ids_in_chunk:
                    unresolved_walls.append(wall_by_raw_id[raw_id])

        except Exception as e:
            if verbose:
                print(f"[VK API ERROR] {e}")

            for raw_id in chunk:
                unresolved_walls.append(wall_by_raw_id[raw_id])

        if pause > 0 and start + chunk_size < len(raw_ids):
            time.sleep(pause)

    return unique_keep_order(resolved_clips), unique_keep_order(unresolved_walls)


def main():
    parser = argparse.ArgumentParser(description="Split mixed URLs into platform files")
    parser.add_argument("--input", default="urls.txt", help="Файл со всеми ссылками")
    parser.add_argument("--dzen-output", default="dzen.txt")
    parser.add_argument("--youtube-output", default="shorts.txt")
    parser.add_argument("--tiktok-output", default="tiktok.txt")
    parser.add_argument("--vk-output", default="vk_clips.txt")
    parser.add_argument("--vk-wall-output", default="vk_wall.txt")
    parser.add_argument("--unknown-output", default="unknown_urls.txt")
    parser.add_argument("--report-output", default="splitter_report.json")
    parser.add_argument("--keep-unknown", action="store_true", help="Сохранять неизвестные ссылки в unknown_urls.txt")

    parser.add_argument("--vk-token", default="", help="VK access token для wall.getById")
    parser.add_argument("--vk-token-file", default="vk_token.txt", help="Файл с VK access token")
    parser.add_argument("--vk-api-version", default="5.275")
    parser.add_argument("--no-vk-api", action="store_true", help="Не резолвить wall ссылки через VK API")
    parser.add_argument("--vk-api-pause", type=float, default=0.34)
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    input_path = Path(args.input)

    if not input_path.exists():
        raise FileNotFoundError(f"Не найден файл: {args.input}")

    text = input_path.read_text(encoding="utf-8")
    raw_urls = extract_urls(text)
    normalized_urls = [normalize_url(u) for u in raw_urls]

    buckets = {
        "dzen": [],
        "youtube": [],
        "tiktok": [],
        "vk_clip": [],
        "vk_wall": [],
        "vk": [],
        "unknown": [],
    }

    for raw_url in raw_urls:
        normalized = normalize_url(raw_url)
        kind = classify(normalized)
        buckets[kind].append(normalized)

    for key in buckets:
        buckets[key] = unique_keep_order(buckets[key])

    resolved_from_walls = []
    unresolved_walls = buckets["vk_wall"] + buckets["vk"]

    token = load_token(args.vk_token, args.vk_token_file)

    if buckets["vk_wall"] and not args.no_vk_api and token:
        resolved_from_walls, api_unresolved_walls = resolve_vk_wall_to_clips(
            buckets["vk_wall"],
            token=token,
            api_version=args.vk_api_version,
            pause=args.vk_api_pause,
            verbose=args.verbose,
        )
        unresolved_walls = api_unresolved_walls + buckets["vk"]
    elif buckets["vk_wall"] and not token and args.verbose:
        print("[VK API] token not found, wall links saved to vk_wall.txt")

    vk_clips = unique_keep_order(buckets["vk_clip"] + resolved_from_walls)

    write_lines(args.dzen_output, buckets["dzen"])
    write_lines(args.youtube_output, buckets["youtube"])
    write_lines(args.tiktok_output, buckets["tiktok"])
    write_lines(args.vk_output, vk_clips)
    write_lines(args.vk_wall_output, unique_keep_order(unresolved_walls))

    if args.keep_unknown:
        write_lines(args.unknown_output, buckets["unknown"])

    raw_duplicates = find_duplicates(raw_urls)
    normalized_duplicates = find_duplicates(normalized_urls)
    normalized_duplicate_details = build_normalized_duplicate_report(raw_urls)

    report = {
        "raw_urls_count": len(raw_urls),
        "raw_urls_unique_count": len(unique_keep_order(raw_urls)),
        "raw_urls_unique_after_normalization_count": len(unique_keep_order(normalized_urls)),
        "duplicates_removed_after_normalization": len(raw_urls) - len(unique_keep_order(normalized_urls)),
        "duplicates": {
            "raw_duplicates_count": len(raw_duplicates),
            "raw_duplicates": raw_duplicates,
            "normalized_duplicates_count": len(normalized_duplicates),
            "normalized_duplicates": normalized_duplicates,
            "normalized_duplicate_details": normalized_duplicate_details,
        },
        "normalized_counts": {
            "dzen": len(buckets["dzen"]),
            "youtube": len(buckets["youtube"]),
            "tiktok": len(buckets["tiktok"]),
            "vk_clip_direct": len(buckets["vk_clip"]),
            "vk_wall_detected": len(buckets["vk_wall"]),
            "vk_generic": len(buckets["vk"]),
            "unknown": len(buckets["unknown"]),
        },
        "vk": {
            "resolved_from_walls": len(resolved_from_walls),
            "unresolved_walls": len(unique_keep_order(unresolved_walls)),
            "vk_clips_output": len(vk_clips),
        },
        "buckets": {
            "dzen": buckets["dzen"],
            "youtube": buckets["youtube"],
            "tiktok": buckets["tiktok"],
            "vk_clip_direct": buckets["vk_clip"],
            "vk_wall_detected": buckets["vk_wall"],
            "vk_generic": buckets["vk"],
            "unknown": buckets["unknown"],
            "resolved_from_walls": resolved_from_walls,
            "unresolved_walls": unique_keep_order(unresolved_walls),
        }
    }

    Path(args.report_output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Готово:")
    print(f"  dzen.txt: {len(buckets['dzen'])}")
    print(f"  shorts.txt: {len(buckets['youtube'])}")
    print(f"  tiktok.txt: {len(buckets['tiktok'])}")
    print(f"  vk_clips.txt: {len(vk_clips)}")
    print(f"  vk_wall.txt: {len(unique_keep_order(unresolved_walls))}")

    if args.keep_unknown:
        print(f"  unknown_urls.txt: {len(buckets['unknown'])}")

    print(f"  raw duplicates: {len(raw_duplicates)}")
    print(f"  normalized duplicates: {len(normalized_duplicates)}")
    print(f"  report: {args.report_output}")


if __name__ == "__main__":
    main()
