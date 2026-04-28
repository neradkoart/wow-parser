#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import dzen_parser_grouped
import parse_vk
import urls_splitter
import wow_urls_fetcher


WORK_DIR = Path.cwd()


def run_module_main(module, argv):
    old_argv = sys.argv[:]
    try:
        sys.argv = argv
        module.main()
    finally:
        sys.argv = old_argv


def run_subprocess_task(name, cmd, progress_callback=None, extra_env=None, timeout_sec=None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    if progress_callback:
        progress_callback(name, 10)
    process = subprocess.run(
        cmd,
        cwd=str(WORK_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
    )
    if process.returncode != 0:
        stderr_tail = (process.stderr or "").strip()
        stdout_tail = (process.stdout or "").strip()
        details = stderr_tail or stdout_tail or "без текста ошибки"
        raise RuntimeError(f"{name}: ошибка выполнения ({process.returncode}) | {details}")
    if progress_callback:
        progress_callback(name, 100)


def read_json(path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_item(platform, item):
    return {
        "platform": platform,
        "url": item.get("url", ""),
        "content_id": item.get("raw_id") or item.get("video_id") or item.get("short_id") or "",
        "author_id": str(item.get("owner_id", "")),
        "author_name": item.get("owner_name", "") or "Unknown",
        "author_url": item.get("owner_url", ""),
        "views": int(item.get("views", 0) or 0),
        "likes": int(item.get("likes", 0) or 0),
        "comments": int(item.get("comments", 0) or 0),
        "shares": int(item.get("shares", 0) or 0),
        "reposts": int(item.get("reposts", 0) or 0),
        "date": item.get("publish_date") or item.get("date_published_display") or "",
        "description": item.get("description", ""),
        "status": item.get("parse_status", "ok"),
    }


def render_report(items, output_path):
    total_views = sum(i["views"] for i in items)
    all_authors = {str(i["author_id"]) for i in items if str(i["author_id"]).strip()}
    by_platform = {
        "vk": {"title": "VK", "file": "vk_index.html", "videos": 0, "views": 0, "authors": set()},
        "youtube": {"title": "YouTube", "file": "youtube_index.html", "videos": 0, "views": 0, "authors": set()},
        "dzen": {"title": "Dzen", "file": "dzen_index.html", "videos": 0, "views": 0, "authors": set()},
        "tiktok": {"title": "TikTok", "file": "tiktok_index.html", "videos": 0, "views": 0, "authors": set()},
    }
    for item in items:
        p = item.get("platform")
        if p in by_platform:
            by_platform[p]["videos"] += 1
            by_platform[p]["views"] += int(item.get("views", 0) or 0)
            author_id = str(item.get("author_id", "")).strip()
            if author_id:
                by_platform[p]["authors"].add(author_id)

    cards = []
    nav_buttons = []
    for key in ("vk", "youtube", "dzen", "tiktok"):
        stat = by_platform[key]
        cards.append(
            f"""
            <div class="card">
              <h3>{stat["title"]}</h3>
              <div>Видео: <b>{stat["videos"]}</b></div>
              <div>Блогеров: <b>{len(stat["authors"])}</b></div>
              <div>Просмотры: <b>{stat["views"]}</b></div>
              <div class="open-link"><a href="{stat["file"]}" target="_blank">Открыть отдельно</a></div>
            </div>
            """
        )
        nav_buttons.append(
            f'<button onclick="openPage(\'{stat["file"]}\', \'{stat["title"]}\')">{stat["title"]}</button>'
        )

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>Единый отчет по соцсетям</title>
<style>
* {{ box-sizing: border-box; }}
body {{
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  margin: 0;
  background: linear-gradient(135deg, #f5d0fe 0%, #fdf2f8 35%, #ecfccb 100%);
  color: #111827;
}}
.container {{ max-width: 1280px; margin: 0 auto; padding: 20px; }}
.hero {{
  background: rgba(255,255,255,0.82);
  border: 1px solid #f1d5fe;
  border-radius: 20px;
  padding: 22px;
  backdrop-filter: blur(8px);
  box-shadow: 0 16px 35px rgba(17,24,39,.08);
  margin-bottom: 16px;
}}
.hero h1 {{ margin: 0 0 10px 0; font-size: 34px; line-height: 1.1; }}
.hero p {{ margin: 0; color: #374151; }}
.summary {{ display:flex; gap:12px; flex-wrap:wrap; margin-top: 16px; }}
.summary .box {{
  background:#ffffff;
  border:1px solid #e9d5ff;
  border-radius:12px;
  padding:10px 12px;
  min-width: 220px;
}}
.cards {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(220px,1fr)); gap:12px; margin-bottom:14px; }}
.card {{
  background:#ffffff;
  border:1px solid #e9d5ff;
  border-radius:14px;
  padding:14px;
  box-shadow: 0 6px 18px rgba(17,24,39,.06);
}}
.card h3 {{ margin:0 0 8px 0; }}
.open-link {{ margin-top:8px; }}
.open-link a {{ color:#7c3aed; text-decoration:none; font-weight:600; }}
.open-link a:hover {{ text-decoration:underline; }}
.nav {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:10px; }}
button {{
  padding:10px 14px;
  border-radius:10px;
  border:1px solid #d8b4fe;
  background:#ffffff;
  color:#581c87;
  font-weight:600;
  cursor:pointer;
}}
button:hover {{ background:#faf5ff; }}
iframe {{
  width:100%;
  height:75vh;
  border:1px solid #f1d5fe;
  border-radius:14px;
  background:#fff;
  box-shadow: 0 8px 20px rgba(17,24,39,.08);
}}
#currentTitle {{ margin: 8px 0; }}
</style>
</head>
<body>
<div class="container">
  <div class="hero">
    <h1>Единый кабинет аналитики соцсетей</h1>
    <p>Современная витрина отчетов по платформам с быстрым переключением между VK, YouTube, Dzen и TikTok.</p>
    <div class="summary">
      <div class="box"><b>Всего видео:</b> {len(items)}</div>
      <div class="box"><b>Всего блогеров:</b> {len(all_authors)}</div>
      <div class="box"><b>Общие просмотры:</b> {total_views}</div>
    </div>
  </div>
  <div class="cards">
    {''.join(cards)}
  </div>
  <div class="nav">
    {''.join(nav_buttons)}
  </div>
  <h2 id="currentTitle">VK</h2>
  <iframe id="platformFrame" src="vk_index.html"></iframe>
</div>
<script>
function openPage(fileName, title) {{
  document.getElementById('platformFrame').src = fileName;
  document.getElementById('currentTitle').textContent = title;
}}
</script>
</body>
</html>"""
    output_path.write_text(html, encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Единое приложение парсинга VK/TikTok/YouTube/Dzen")
    parser.add_argument("--fetch-wow", action="store_true", help="Сначала забрать ссылки из wow_urls_fetcher")
    parser.add_argument("--open-report", action="store_true", help="Открыть отчет в браузере")
    parser.add_argument("--skip-vk", action="store_true")
    parser.add_argument("--skip-tiktok", action="store_true")
    parser.add_argument("--skip-youtube", action="store_true")
    parser.add_argument("--skip-dzen", action="store_true")
    parser.add_argument("--report-html", default="report.html")
    parser.add_argument("--report-json", default="report.json")
    return parser.parse_args()


def run_pipeline(args, progress_callback=None):
    def set_progress(stage, value):
        if progress_callback:
            progress_callback(stage, value)

    set_progress("global", 2)
    if args.fetch_wow:
        set_progress("wow", 10)
        run_module_main(wow_urls_fetcher, ["wow_urls_fetcher.py", "--output", "urls.txt"])
        set_progress("wow", 100)

    set_progress("splitter", 20)
    run_module_main(
        urls_splitter,
        ["urls_splitter.py", "--input", "urls.txt", "--report-output", "splitter_report.json"],
    )
    set_progress("splitter", 100)
    set_progress("global", 35)

    python_cmd = sys.executable
    venv_python = WORK_DIR / ".venv-build" / "bin" / "python"
    if venv_python.exists():
        python_cmd = str(venv_python)
    if getattr(sys, "frozen", False) and "python" not in Path(sys.executable).name.lower():
        python_cmd = str(venv_python) if venv_python.exists() else os.environ.get("PYTHON_BIN", "python3.14")

    tasks = []
    vk_token = (WORK_DIR / "vk_token.txt").read_text(encoding="utf-8").strip() if (WORK_DIR / "vk_token.txt").exists() else ""
    if not args.skip_vk:
        tasks.append(
            (
                "vk",
                [
                    python_cmd,
                    "parse_vk.py",
                ],
                {"VK_ACCESS_TOKEN": vk_token} if vk_token else {},
                1800,
            )
        )
    else:
        set_progress("vk", 100)

    if not args.skip_tiktok:
        tasks.append(
            (
                "tiktok",
                [
                    python_cmd,
                    "tiktok_parser_grouped.py",
                    "--input",
                    "tiktok.txt",
                    "--output",
                    "tiktok_index.html",
                    "--save-json",
                    "tiktok_result.json",
                    "--force-playwright",
                    "--headless",
                ],
                {},
                1800,
            )
        )
    else:
        set_progress("tiktok", 100)

    if not args.skip_youtube:
        tasks.append(
            (
                "youtube",
                [
                    python_cmd,
                    "youtube_shorts_parser_grouped.py",
                    "--input",
                    "shorts.txt",
                    "--output",
                    "youtube_index.html",
                    "--save-json",
                    "youtube_result.json",
                ],
                {},
                900,
            )
        )
    else:
        set_progress("youtube", 100)

    if not args.skip_dzen:
        tasks.append(
            (
                "dzen",
                [
                    python_cmd,
                    "dzen_parser_grouped.py",
                    "--input",
                    "dzen.txt",
                    "--output",
                    "dzen_index.html",
                    "--save-json",
                    "dzen_result.json",
                ],
                {},
                900,
            )
        )
    else:
        set_progress("dzen", 100)

    errors = []
    done_count = 0
    total_count = len(tasks) if tasks else 1
    with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as executor:
        future_map = {
            executor.submit(run_subprocess_task, name, cmd, set_progress, env, timeout_sec): name
            for name, cmd, env, timeout_sec in tasks
        }
        for future in as_completed(future_map):
            name = future_map[future]
            try:
                future.result()
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                set_progress(name, 100)
            done_count += 1
            set_progress("global", 35 + int((done_count / total_count) * 60))

    if errors:
        raise RuntimeError("Ошибки парсинга: " + "; ".join(errors))

    set_progress("global", 95)

    unified = []

    if not args.skip_vk:
        for item in read_json(WORK_DIR / "result.json"):
            unified.append(normalize_item("vk", item))
    if not args.skip_tiktok:
        for item in read_json(WORK_DIR / "tiktok_result.json"):
            unified.append(normalize_item("tiktok", item))
    if not args.skip_youtube:
        for item in read_json(WORK_DIR / "youtube_result.json"):
            unified.append(normalize_item("youtube", item))
    if not args.skip_dzen:
        for item in read_json(WORK_DIR / "dzen_result.json"):
            unified.append(normalize_item("dzen", item))

    if not args.skip_vk:
        vk_html = WORK_DIR / "index.html"
        if vk_html.exists():
            vk_html.replace(WORK_DIR / "vk_index.html")

    (WORK_DIR / args.report_json).write_text(json.dumps(unified, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = WORK_DIR / args.report_html
    render_report(unified, report_path)
    set_progress("global", 100)

    print(f"Готово: {args.report_json}, {args.report_html}")
    if args.open_report:
        webbrowser.open(report_path.as_uri())


def main():
    args = parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
