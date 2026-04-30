#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import re
import subprocess
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import shutil

from src.core import urls_splitter, wow_urls_fetcher
from src.parsers import (
    dzen_parser_grouped,
    parse_vk,
    pinterest_parser_grouped,
    tiktok_parser_grouped,
    youtube_shorts_parser_grouped,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_DIR = PROJECT_ROOT


def get_work_dir():
    custom = os.environ.get("WOW_PARSER_WORKDIR", "").strip()
    path = Path(custom) if custom else Path.cwd()
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def run_module_main(module, argv):
    old_argv = sys.argv[:]
    try:
        sys.argv = argv
        module.main()
    finally:
        sys.argv = old_argv


def run_subprocess_task(name, cmd, progress_callback=None, extra_env=None, timeout_sec=None, work_dir=None):
    work_dir = work_dir or get_work_dir()
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        env.update(extra_env)
    if progress_callback:
        progress_callback(name, 10)
    process = subprocess.Popen(
        cmd,
        cwd=str(work_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    output_lines = []
    try:
        assert process.stdout is not None
        for line in process.stdout:
            output_lines.append(line.rstrip("\n"))
            print(line, end="")

            progress_match = (
                re.search(r"@@PROGRESS\s+(\d+)/(\d+)", line)
                or re.search(r"\[(\d+)/(\d+)\]", line)
                or re.search(r"Fetching\s+(\d+)\s*/\s*(\d+)", line)
            )
            if progress_match and progress_callback:
                current = int(progress_match.group(1))
                total = int(progress_match.group(2))
                if total > 0:
                    percent = max(10, min(99, int((current / total) * 100)))
                    progress_callback(name, percent)

        process.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        process.kill()
        raise RuntimeError(f"{name}: таймаут выполнения ({timeout_sec} сек)")

    if process.returncode != 0:
        details = "\n".join(output_lines[-30:]).strip() or "без текста ошибки"
        raise RuntimeError(f"{name}: ошибка выполнения ({process.returncode}) | {details}")
    if progress_callback:
        progress_callback(name, 100)


def run_inprocess_task(name, module, argv, progress_callback=None, extra_env=None):
    old_env = {}
    old_stdout = sys.stdout
    old_stderr = sys.stderr

    class ProgressTee:
        def __init__(self, base_stream):
            self.base_stream = base_stream
            self.buf = ""

        def write(self, text):
            if not text:
                return 0
            self.base_stream.write(text)
            self.base_stream.flush()
            self.buf += text
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                m = re.search(r"\[(\d+)/(\d+)\]", line) or re.search(r"Fetching\s+(\d+)\s*/\s*(\d+)", line)
                if m and progress_callback:
                    current = int(m.group(1))
                    total = int(m.group(2))
                    if total > 0:
                        percent = max(10, min(99, int((current / total) * 100)))
                        progress_callback(name, percent)
            return len(text)

        def flush(self):
            self.base_stream.flush()

    if extra_env:
        for key, value in extra_env.items():
            old_env[key] = os.environ.get(key)
            os.environ[key] = value
    try:
        if progress_callback:
            progress_callback(name, 10)
        tee = ProgressTee(old_stdout)
        sys.stdout = tee
        sys.stderr = tee
        run_module_main(module, argv)
        if progress_callback:
            progress_callback(name, 100)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        if extra_env:
            for key, old_value in old_env.items():
                if old_value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old_value


def build_module_cmd(python_cmd, module_name):
    frozen_mode = bool(getattr(sys, "frozen", False))
    if frozen_mode:
        # Spawn same bundled executable; app_ui entrypoint will execute task mode from env.
        return [python_cmd], {"WOW_TASK_MODULE": module_name}
    # Non-frozen: run entrypoint launcher in task mode.
    return [python_cmd, "-u", str(SOURCE_DIR / "entrypoints" / "app_ui.py")], {"WOW_TASK_MODULE": module_name}


def read_json(path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_item(platform, item):
    return {
        "platform": platform,
        "url": item.get("url", ""),
        "content_id": item.get("raw_id") or item.get("video_id") or item.get("short_id") or item.get("pin_id") or "",
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
    restart_url = os.environ.get("WOW_UI_URL", "http://127.0.0.1:8765/")
    total_views = sum(i["views"] for i in items)
    all_authors = {str(i["author_id"]) for i in items if str(i["author_id"]).strip()}
    by_platform = {
        "vk": {"title": "VK", "file": "vk_index.html", "videos": 0, "views": 0, "authors": set()},
        "youtube": {"title": "YouTube", "file": "youtube_index.html", "videos": 0, "views": 0, "authors": set()},
        "dzen": {"title": "Dzen", "file": "dzen_index.html", "videos": 0, "views": 0, "authors": set()},
        "tiktok": {"title": "TikTok", "file": "tiktok_index.html", "videos": 0, "views": 0, "authors": set()},
        "pinterest": {"title": "Pinterest", "file": "pinterest_index.html", "videos": 0, "views": 0, "authors": set()},
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
    for key in ("vk", "youtube", "dzen", "tiktok", "pinterest"):
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
<link rel="icon" type="image/png" href="favicon.png">
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
    <p>Современная витрина отчетов по платформам с быстрым переключением между VK, YouTube, Dzen, TikTok и Pinterest.</p>
    <p style="margin-top:10px;"><a href="{restart_url}" style="display:inline-block;padding:9px 12px;border-radius:10px;border:1px solid #d8b4fe;background:#fff;color:#581c87;font-weight:600;text-decoration:none;">Парсить заново</a></p>
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
    parser = argparse.ArgumentParser(description="Единое приложение парсинга VK/TikTok/YouTube/Dzen/Pinterest")
    parser.add_argument("--fetch-wow", action="store_true", help="Сначала забрать ссылки из wow_urls_fetcher")
    parser.add_argument("--open-report", action="store_true", help="Открыть отчет в браузере")
    parser.add_argument("--skip-vk", action="store_true")
    parser.add_argument("--skip-tiktok", action="store_true")
    parser.add_argument("--skip-youtube", action="store_true")
    parser.add_argument("--skip-dzen", action="store_true")
    parser.add_argument("--skip-pinterest", action="store_true")
    parser.add_argument("--report-html", default="report.html")
    parser.add_argument("--report-json", default="report.json")
    return parser.parse_args()


def run_pipeline(args, progress_callback=None):
    work_dir = get_work_dir()
    old_cwd = Path.cwd()
    os.chdir(work_dir)

    def set_progress(stage, value):
        if progress_callback:
            progress_callback(stage, value)

    try:
        source_dzen_cookies = SOURCE_DIR / "dzen_cookies.txt"
        target_dzen_cookies = work_dir / "dzen_cookies.txt"
        if source_dzen_cookies.exists() and not target_dzen_cookies.exists():
            shutil.copy2(source_dzen_cookies, target_dzen_cookies)
        source_favicon = SOURCE_DIR / "favicon.png"
        target_favicon = work_dir / "favicon.png"
        if source_favicon.exists() and not target_favicon.exists():
            shutil.copy2(source_favicon, target_favicon)

        set_progress("global", 2)
        if args.fetch_wow:
            set_progress("wow", 10)
            run_module_main(wow_urls_fetcher, ["wow_urls_fetcher.py", "--output", "urls.txt"])
            set_progress("wow", 100)

        set_progress("splitter", 20)
        run_module_main(urls_splitter, ["urls_splitter.py", "--input", "urls.txt", "--report-output", "splitter_report.json"])
        set_progress("splitter", 100)
        set_progress("global", 35)

        frozen_mode = bool(getattr(sys, "frozen", False))
        python_candidates = [
            os.environ.get("WOW_PARSER_PYTHON", ""),
            str(work_dir / ".venv-runtime" / "bin" / "python"),
            str(work_dir / ".venv-builder" / "bin" / "python"),
            str(SOURCE_DIR / ".venv-build" / "bin" / "python"),
            sys.executable if "python" in Path(sys.executable).name.lower() else "",
            os.environ.get("PYTHON_BIN", "python3"),
        ]
        if frozen_mode:
            python_candidates.insert(0, sys.executable)
        python_cmd = ""
        for candidate in python_candidates:
            if not candidate:
                continue
            if Path(candidate).exists() or candidate.startswith("python"):
                python_cmd = candidate
                break
        if not python_cmd:
            raise RuntimeError("Не найден Python для запуска подпарсеров")

        use_playwright = os.environ.get("TIKTOK_USE_PLAYWRIGHT", "1") == "1"

        tasks = []
        base_py_path = os.environ.get("PYTHONPATH", "")
        merged_py_path = str(SOURCE_DIR) if not base_py_path else (str(SOURCE_DIR) + os.pathsep + base_py_path)
        vk_token = (work_dir / "vk_token.txt").read_text(encoding="utf-8").strip() if (work_dir / "vk_token.txt").exists() else ""
        if not args.skip_vk:
            cmd, cmd_env = build_module_cmd(python_cmd, "parse_vk")
            tasks.append(("vk", ["parse_vk.py"], cmd, {**cmd_env, "PYTHONPATH": merged_py_path, **({"VK_ACCESS_TOKEN": vk_token} if vk_token else {})}, 1800))
        else:
            set_progress("vk", 100)

        if not args.skip_tiktok:
            tiktok_module_argv = ["tiktok_parser_grouped.py", "--input", "tiktok.txt", "--output", "tiktok_index.html", "--save-json", "tiktok_result.json"]
            cmd, cmd_env = build_module_cmd(python_cmd, "tiktok_parser_grouped")
            if use_playwright:
                tiktok_module_argv.extend(["--force-playwright", "--headless"])
            tiktok_module_argv.append("--verbose")
            tasks.append(("tiktok", tiktok_module_argv, cmd, {**cmd_env, "PYTHONPATH": merged_py_path}, 1800))
        else:
            set_progress("tiktok", 100)

        if not args.skip_youtube:
            cmd, cmd_env = build_module_cmd(python_cmd, "youtube_shorts_parser_grouped")
            tasks.append(("youtube", ["youtube_shorts_parser_grouped.py", "--input", "shorts.txt", "--output", "youtube_index.html", "--save-json", "youtube_result.json", "--verbose"], cmd, {**cmd_env, "PYTHONPATH": merged_py_path}, 900))
        else:
            set_progress("youtube", 100)

        if not args.skip_dzen:
            cmd, cmd_env = build_module_cmd(python_cmd, "dzen_parser_grouped")
            tasks.append(("dzen", ["dzen_parser_grouped.py", "--input", "dzen.txt", "--output", "dzen_index.html", "--save-json", "dzen_result.json", "--verbose"], cmd, {**cmd_env, "PYTHONPATH": merged_py_path}, 900))
        else:
            set_progress("dzen", 100)

        pinterest_cookie = (work_dir / "pinterest_token.txt").read_text(encoding="utf-8").strip() if (work_dir / "pinterest_token.txt").exists() else ""
        pinterest_input = work_dir / "pinterest.txt"
        pinterest_has_urls = pinterest_input.exists() and bool(pinterest_input.read_text(encoding="utf-8").strip())
        if not args.skip_pinterest and pinterest_has_urls:
            cmd, cmd_env = build_module_cmd(python_cmd, "pinterest_parser_grouped")
            pinterest_module_argv = ["pinterest_parser_grouped.py", "--input", "pinterest.txt", "--output", "pinterest_index.html", "--save-json", "pinterest_result.json", "--verbose"]
            if os.environ.get("PINTEREST_USE_PLAYWRIGHT", "0") == "1":
                pinterest_module_argv.append("--force-playwright-redirect")
            tasks.append((
                "pinterest",
                pinterest_module_argv,
                cmd,
                {**cmd_env, "PYTHONPATH": merged_py_path, **({"PINTEREST_COOKIE": pinterest_cookie} if pinterest_cookie else {})},
                1200,
            ))
        else:
            set_progress("pinterest", 100)

        errors = []
        done_count = 0
        total_count = len(tasks) if tasks else 1
        with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as executor:
            future_map = {}
            for name, argv_for_module, cmd, env, timeout_sec in tasks:
                env = dict(env)
                env["WOW_TASK_ARGV"] = json.dumps(argv_for_module, ensure_ascii=False)
                future_map[executor.submit(run_subprocess_task, name, cmd, set_progress, env, timeout_sec, work_dir)] = name

            for future in as_completed(future_map):
                name = future_map[future]
                try:
                    future.result()
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                    set_progress(f"{name}_error", str(exc))
                done_count += 1
                set_progress("global", 35 + int((done_count / total_count) * 60))

        if errors:
            print("WARN: Ошибки парсинга: " + "; ".join(errors))

        set_progress("global", 95)
        unified = []
        if not args.skip_vk:
            for item in read_json(work_dir / "result.json"):
                unified.append(normalize_item("vk", item))
        if not args.skip_tiktok:
            for item in read_json(work_dir / "tiktok_result.json"):
                unified.append(normalize_item("tiktok", item))
        if not args.skip_youtube:
            for item in read_json(work_dir / "youtube_result.json"):
                unified.append(normalize_item("youtube", item))
        if not args.skip_dzen:
            for item in read_json(work_dir / "dzen_result.json"):
                unified.append(normalize_item("dzen", item))
        if not args.skip_pinterest and (work_dir / "pinterest_result.json").exists():
            for item in read_json(work_dir / "pinterest_result.json"):
                unified.append(normalize_item("pinterest", item))

        if not args.skip_vk:
            vk_html = work_dir / "index.html"
            if vk_html.exists():
                vk_html.replace(work_dir / "vk_index.html")

        (work_dir / args.report_json).write_text(json.dumps(unified, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path = work_dir / args.report_html
        render_report(unified, report_path)
        set_progress("global", 100)

        print(f"Готово: {args.report_json}, {args.report_html}")
        if errors:
            print("Частично завершено: некоторые соцсети завершились с ошибками.")
        if args.open_report:
            webbrowser.open(report_path.as_uri())
    finally:
        os.chdir(old_cwd)


def main():
    args = parse_args()
    run_pipeline(args)


if __name__ == "__main__":
    main()
