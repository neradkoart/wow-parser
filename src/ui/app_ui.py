#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import html
import io
import json
import logging
import os
import socket
import sys
import threading
import traceback
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from src.core import unified_app, urls_splitter, wow_urls_fetcher
from src.parsers import (
    dzen_parser_grouped,
    parse_vk,
    pinterest_parser_grouped,
    tiktok_parser_grouped,
    youtube_shorts_parser_grouped,
)


HOST = "127.0.0.1"
PORT = 8765

JOB = {
    "running": False,
    "done": False,
    "error": "",
    "log": "",
    "progress": {
        "global": 0,
        "wow": 0,
        "splitter": 0,
        "vk": 0,
        "tiktok": 0,
        "youtube": 0,
        "dzen": 0,
        "pinterest": 0,
    },
    "task_errors": {},
}
SERVER_REF = {"server": None}
APP_LOG_PATH = Path.home() / "Library" / "Logs" / "WowParser" / "app.log"
APP_DATA_DIR = Path.home() / "Library" / "Application Support" / "WowParser"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FAVICON_PATH = PROJECT_ROOT / "favicon.png"


def setup_file_logging():
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["WOW_PARSER_WORKDIR"] = str(APP_DATA_DIR)
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(APP_DATA_DIR / "ms-playwright"))
    APP_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(APP_LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    logging.info("Application bootstrap started")


def run_task_mode_if_requested():
    module_name = os.environ.get("WOW_TASK_MODULE", "").strip()
    if not module_name:
        return False
    argv_raw = os.environ.get("WOW_TASK_ARGV", "[]")
    argv = json.loads(argv_raw)
    module_map = {
        "parse_vk": parse_vk,
        "tiktok_parser_grouped": tiktok_parser_grouped,
        "youtube_shorts_parser_grouped": youtube_shorts_parser_grouped,
        "dzen_parser_grouped": dzen_parser_grouped,
        "pinterest_parser_grouped": pinterest_parser_grouped,
        "wow_urls_fetcher": wow_urls_fetcher,
        "urls_splitter": urls_splitter,
    }
    if module_name not in module_map:
        raise RuntimeError(f"Unknown task module: {module_name}")
    old_argv = sys.argv[:]
    try:
        sys.argv = argv
        module_map[module_name].main()
    finally:
        sys.argv = old_argv
    return True


def pick_free_port(host, start_port, max_tries=30):
    for offset in range(max_tries):
        port = start_port + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise OSError(f"No free port in range {start_port}-{start_port + max_tries - 1}")


FORM_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>WOW Parser UI</title>
<link rel="icon" type="image/png" href="/favicon.png">
<style>
* { box-sizing: border-box; }
body {
  font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  margin: 0;
  background: linear-gradient(135deg, #f5d0fe 0%, #fdf2f8 35%, #ecfccb 100%);
  color: #111827;
}
.container { max-width: 1180px; margin: 0 auto; padding: 20px; }
.hero {
  background: rgba(255,255,255,0.82);
  border: 1px solid #f1d5fe;
  border-radius: 20px;
  padding: 22px;
  backdrop-filter: blur(8px);
  box-shadow: 0 16px 35px rgba(17,24,39,.08);
  margin-bottom: 16px;
}
.hero h1 { margin: 0 0 8px 0; font-size: 30px; line-height: 1.1; }
.hero p { margin: 0; color: #374151; }
form { margin-top: 12px; }
.card {
  background: #ffffff;
  border: 1px solid #e9d5ff;
  border-radius: 14px;
  padding: 14px;
  margin-bottom: 10px;
  box-shadow: 0 6px 18px rgba(17,24,39,.06);
}
textarea {
  width: 100%;
  min-height: 130px;
  border: 1px solid #ddd6fe;
  border-radius: 10px;
  padding: 10px;
  background: #fff;
  font-family: inherit;
}
label { font-weight: 600; color: #1f2937; }
button {
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid #d8b4fe;
  background: #ffffff;
  color: #581c87;
  font-weight: 600;
  cursor: pointer;
}
button:hover { background: #faf5ff; }
.log { white-space: pre-wrap; background:#111827; color:#e5e7eb; padding:12px; border-radius:8px; }
.wait { display:none; padding:10px; background:#fff7ed; border:1px solid #fed7aa; border-radius:8px; margin-bottom:10px; }
.bar-wrap { margin: 8px 0; }
.bar { height: 12px; background: #e5e7eb; border-radius: 999px; overflow: hidden; }
.bar-fill { height: 100%; width: 0%; background: linear-gradient(90deg, #2563eb, #0ea5e9); transition: width .25s; }
.bar-fill.error { background: linear-gradient(90deg, #dc2626, #ef4444); }
.row { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px; }
.dup-box { margin-top: 10px; padding: 10px; border: 1px solid #f5c2c7; background: #fff1f2; border-radius: 10px; display: none; }
.dup-box h4 { margin: 0 0 6px 0; color: #9f1239; font-size: 14px; }
.dup-box pre { margin: 0; max-height: 140px; overflow: auto; white-space: pre-wrap; font-size: 12px; }
.error-box { display:none; margin-top:10px; padding:10px; border:1px solid #fecaca; background:#fef2f2; border-radius:10px; }
.error-box h4 { margin:0 0 6px 0; color:#991b1b; }
.error-box pre { margin:0; max-height:140px; overflow:auto; white-space:pre-wrap; font-size:12px; }
</style>
</head>
<body>
<div class="container">
<div class="hero">
  <h1>WOW Parser Unified UI</h1>
  <p>Внеси входные данные, запусти парсинг и получи структурированные отчеты по всем платформам.</p>
</div>
<form method="POST" action="/run">
  <div class="card">
    <label>Источник ссылок:</label><br>
    <label><input type="radio" name="mode" value="urls" checked> URLs из поля</label>
    <label><input type="radio" name="mode" value="wow"> WOW API (через wowData)</label>
  </div>
  <div class="card">
    <label>VK Token (опционально):</label><br>
    <textarea name="vk_token"></textarea>
  </div>
  <div class="card">
    <label>Pinterest token/cookie (обязательно для приватной статистики):</label><br>
    <textarea name="pinterest_token"></textarea>
  </div>
  <div class="card">
    <label>URLs (по одной ссылке в строке):</label><br>
    <textarea name="urls" id="urlsField"></textarea>
    <div id="dupBox" class="dup-box">
      <h4 id="dupTitle">Найдены дубли</h4>
      <pre id="dupList"></pre>
    </div>
  </div>
  <div class="card">
    <label>wowData (key=value):</label><br>
    <textarea name="wow_data"></textarea>
  </div>
  <div class="card">
    <label><input type="checkbox" name="open_report" checked> Открывать report.html</label><br>
    <label><input type="checkbox" name="skip_vk"> Пропустить VK</label><br>
    <label><input type="checkbox" name="skip_tiktok"> Пропустить TikTok</label><br>
    <label><input type="checkbox" name="skip_youtube"> Пропустить YouTube</label><br>
    <label><input type="checkbox" name="skip_dzen"> Пропустить Dzen</label><br>
    <label><input type="checkbox" name="skip_pinterest"> Пропустить Pinterest</label>
  </div>
  <button type="submit">Запустить парсинг</button>
  <button type="button" id="stopAppBtn" style="margin-left:8px;background:#fee2e2;border:1px solid #fecaca;">Остановить приложение</button>
</form>
<div id="waitBox" class="wait">
  <b>Пожалуйста, подождите, идет парсинг...</b>
  <div class="bar-wrap"><div class="row"><span>Общий прогресс</span><span id="gVal">0%</span></div><div class="bar"><div id="gBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>VK</span><span id="vkVal">0%</span></div><div class="bar"><div id="vkBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>TikTok</span><span id="tiktokVal">0%</span></div><div class="bar"><div id="tiktokBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>YouTube</span><span id="youtubeVal">0%</span></div><div class="bar"><div id="youtubeBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>Dzen</span><span id="dzenVal">0%</span></div><div class="bar"><div id="dzenBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>Pinterest</span><span id="pinterestVal">0%</span></div><div class="bar"><div id="pinterestBar" class="bar-fill"></div></div></div>
  <div id="taskErrors" class="error-box">
    <h4>Ошибки парсинга</h4>
    <pre id="taskErrorsText"></pre>
  </div>
</div>
<script>
const form = document.querySelector('form');
const waitBox = document.getElementById('waitBox');
let timer = null;
let internalNavToResult = false;
const urlsField = document.getElementById('urlsField');
const dupBox = document.getElementById('dupBox');
const dupTitle = document.getElementById('dupTitle');
const dupList = document.getElementById('dupList');
const taskErrorsBox = document.getElementById('taskErrors');
const taskErrorsText = document.getElementById('taskErrorsText');

function setBar(id, value) {
  const v = Math.max(0, Math.min(100, Number(value || 0)));
  document.getElementById(id + 'Bar').style.width = v + '%';
  document.getElementById(id + 'Val').textContent = v + '%';
}

function markBarError(id, hasError) {
  const el = document.getElementById(id + 'Bar');
  if (!el) return;
  el.classList.toggle('error', !!hasError);
}

function normalizeUrlLine(value) {
  return value.trim();
}

function updateDuplicateInfo() {
  const lines = (urlsField.value || '')
    .split('\\n')
    .map(normalizeUrlLine)
    .filter(Boolean);

  const counts = new Map();
  for (const line of lines) {
    counts.set(line, (counts.get(line) || 0) + 1);
  }

  const duplicates = [];
  for (const [url, count] of counts.entries()) {
    if (count > 1) duplicates.push({ url, count });
  }

  if (!duplicates.length) {
    dupBox.style.display = 'none';
    dupList.textContent = '';
    return;
  }

  duplicates.sort((a, b) => b.count - a.count);
  dupTitle.textContent = `Найдены дубли: ${duplicates.length} ссылок`;
  dupList.textContent = duplicates.map(d => `${d.count}x  ${d.url}`).join('\\n');
  dupBox.style.display = 'block';
}

async function pollStatus() {
  const r = await fetch('/status');
  const s = await r.json();
  const vk = Number((s.progress || {}).vk || 0);
  const tiktok = Number((s.progress || {}).tiktok || 0);
  const youtube = Number((s.progress || {}).youtube || 0);
  const dzen = Number((s.progress || {}).dzen || 0);
  const pinterest = Number((s.progress || {}).pinterest || 0);

  setBar('vk', vk);
  setBar('tiktok', tiktok);
  setBar('youtube', youtube);
  setBar('dzen', dzen);
  setBar('pinterest', pinterest);

  // Continuous overall progress from the 4 social workers.
  const globalPercent = Math.round((vk + tiktok + youtube + dzen + pinterest) / 5);
  setBar('g', globalPercent);
  const errs = s.task_errors || {};
  markBarError('vk', !!errs.vk);
  markBarError('tiktok', !!errs.tiktok);
  markBarError('youtube', !!errs.youtube);
  markBarError('dzen', !!errs.dzen);
  markBarError('pinterest', !!errs.pinterest);
  if (Object.keys(errs).length) {
    taskErrorsBox.style.display = 'block';
    taskErrorsText.textContent = Object.entries(errs).map(([k, v]) => `${k}: ${v}`).join('\\n\\n');
  } else {
    taskErrorsBox.style.display = 'none';
    taskErrorsText.textContent = '';
  }
  if (!s.running) {
    clearInterval(timer);
    timer = null;
    internalNavToResult = true;
    window.location.href = '/result';
  }
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const data = new FormData(form);
  const params = new URLSearchParams(data);
  const r = await fetch('/start', { method: 'POST', body: params });
  if (!r.ok) {
    const t = await r.text();
    alert(t);
    return;
  }
  waitBox.style.display = 'block';
  if (!timer) {
    timer = setInterval(pollStatus, 1000);
  }
  pollStatus();
});

urlsField.addEventListener('input', updateDuplicateInfo);
updateDuplicateInfo();

document.getElementById('stopAppBtn').addEventListener('click', async () => {
  const ok = confirm('Закрыть приложение?');
  if (!ok) return;
  try {
    await fetch('/shutdown', { method: 'POST' });
  } catch (e) {}
  document.body.innerHTML = '<h2 style="font-family:Arial,sans-serif">Приложение остановлено. Можно закрыть вкладку.</h2>';
});

window.addEventListener('beforeunload', () => {
  if (internalNavToResult) return;
  try { navigator.sendBeacon('/shutdown'); } catch (e) {}
});
</script>
</div>
</body>
</html>"""


def run_pipeline(form):
    mode = (form.get("mode", ["urls"])[0] or "urls").strip()
    vk_token = (form.get("vk_token", [""])[0] or "").strip()
    pinterest_token = (form.get("pinterest_token", [""])[0] or "").strip()
    urls = (form.get("urls", [""])[0] or "").strip()
    wow_data = (form.get("wow_data", [""])[0] or "").strip()

    if mode == "urls" and not urls:
        raise RuntimeError("В режиме URLs нужно заполнить поле URLs.")
    if mode == "wow" and not wow_data:
        raise RuntimeError("В режиме WOW API нужно заполнить поле wowData.")

    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if vk_token:
        (APP_DATA_DIR / "vk_token.txt").write_text(vk_token + "\n", encoding="utf-8")
    if pinterest_token:
        (APP_DATA_DIR / "pinterest_token.txt").write_text(pinterest_token + "\n", encoding="utf-8")
    if urls:
        (APP_DATA_DIR / "urls.txt").write_text(urls + "\n", encoding="utf-8")
    if wow_data:
        (APP_DATA_DIR / "wowData.txt").write_text(wow_data + "\n", encoding="utf-8")

    argv = ["unified_app.py"]
    if mode == "wow":
        argv.append("--fetch-wow")
    if "open_report" in form:
        argv.append("--open-report")
    if "skip_vk" in form:
        argv.append("--skip-vk")
    if "skip_tiktok" in form:
        argv.append("--skip-tiktok")
    if "skip_youtube" in form:
        argv.append("--skip-youtube")
    if "skip_dzen" in form:
        argv.append("--skip-dzen")
    if "skip_pinterest" in form:
        argv.append("--skip-pinterest")

    old_argv = sys.argv[:]
    buffer = io.StringIO()
    try:
        sys.argv = argv
        with redirect_stdout(buffer), redirect_stderr(buffer):
            unified_app.main()
    finally:
        sys.argv = old_argv
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/shutdown":
            body = b"stopping"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            server = SERVER_REF.get("server")
            if server:
                threading.Thread(target=server.shutdown, daemon=True).start()
            return

        if self.path != "/start":
            self.send_error(404)
            return

        if JOB["running"]:
            body = "Уже выполняется парсинг".encode("utf-8")
            self.send_response(409)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(raw, keep_blank_values=True)

        def worker():
            JOB["running"] = True
            JOB["done"] = False
            JOB["error"] = ""
            JOB["log"] = ""
            JOB["task_errors"] = {}
            for k in JOB["progress"]:
                JOB["progress"][k] = 0

            old_argv = sys.argv[:]
            buffer = io.StringIO()
            writer = io.StringIO()

            def on_progress(stage, value):
                if stage in JOB["progress"]:
                    JOB["progress"][stage] = max(JOB["progress"][stage], int(value))
                elif stage.endswith("_error"):
                    task_name = stage[:-6]
                    JOB["task_errors"][task_name] = str(value)

            try:
                mode = (form.get("mode", ["urls"])[0] or "urls").strip()
                vk_token = (form.get("vk_token", [""])[0] or "").strip()
                pinterest_token = (form.get("pinterest_token", [""])[0] or "").strip()
                urls = (form.get("urls", [""])[0] or "").strip()
                wow_data = (form.get("wow_data", [""])[0] or "").strip()

                if mode == "urls" and not urls:
                    raise RuntimeError("В режиме URLs нужно заполнить поле URLs.")
                if mode == "wow" and not wow_data:
                    raise RuntimeError("В режиме WOW API нужно заполнить поле wowData.")

                if vk_token:
                    (APP_DATA_DIR / "vk_token.txt").write_text(vk_token + "\n", encoding="utf-8")
                if pinterest_token:
                    (APP_DATA_DIR / "pinterest_token.txt").write_text(pinterest_token + "\n", encoding="utf-8")
                if urls:
                    (APP_DATA_DIR / "urls.txt").write_text(urls + "\n", encoding="utf-8")
                if wow_data:
                    (APP_DATA_DIR / "wowData.txt").write_text(wow_data + "\n", encoding="utf-8")

                argv = ["unified_app.py"]
                if mode == "wow":
                    argv.append("--fetch-wow")
                if "open_report" in form:
                    argv.append("--open-report")
                if "skip_vk" in form:
                    argv.append("--skip-vk")
                if "skip_tiktok" in form:
                    argv.append("--skip-tiktok")
                if "skip_youtube" in form:
                    argv.append("--skip-youtube")
                if "skip_dzen" in form:
                    argv.append("--skip-dzen")
                if "skip_pinterest" in form:
                    argv.append("--skip-pinterest")

                sys.argv = argv
                args = unified_app.parse_args()
                with redirect_stdout(buffer), redirect_stderr(buffer):
                    unified_app.run_pipeline(args, progress_callback=on_progress)
                JOB["log"] = buffer.getvalue() + writer.getvalue()
            except Exception:
                JOB["error"] = traceback.format_exc()
                JOB["log"] = buffer.getvalue() + writer.getvalue()
            finally:
                sys.argv = old_argv
                JOB["running"] = False
                JOB["done"] = True

        threading.Thread(target=worker, daemon=True).start()

        body = b"started"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_status(self):
        body = json.dumps(
            {
                "running": JOB["running"],
                "done": JOB["done"],
                "error": JOB["error"],
                "progress": JOB["progress"],
                "task_errors": JOB["task_errors"],
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_result(self):
        if JOB["running"]:
            body = '<html><meta charset="utf-8"><body><h3>Парсинг еще выполняется...</h3><a href="/">Назад</a></body></html>'.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if JOB["error"]:
            result_html = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Ошибка</title>
            <body style="font-family:Arial,sans-serif;margin:20px;background:#f4f7fb">
            <h2>Завершено с ошибками</h2>
            <p><a href="/" style="display:inline-block;padding:8px 12px;border:1px solid #c7d2e0;border-radius:10px;background:#eef3f8;color:#1f2937;text-decoration:none;font-weight:600;">Парсить снова</a></p>
            <h3>Лог</h3><div class="log">{html.escape(JOB["log"])}</div>
            <h3>Трассировка</h3><div class="log">{html.escape(JOB["error"])}</div></body></html>"""
            body = result_html.encode("utf-8")
            self.send_response(200)
        else:
            result_html = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Результат</title>
            <body style="font-family:Arial,sans-serif;margin:20px;background:#f4f7fb">
            <h2>Готово</h2>
            <p>Сформированы файлы <code>report.html</code> и <code>report.json</code>.</p>
            <p><a href="/" style="display:inline-block;padding:8px 12px;border:1px solid #c7d2e0;border-radius:10px;background:#eef3f8;color:#1f2937;text-decoration:none;font-weight:600;">Парсить снова</a></p>
            <h3>Лог</h3><div class="log">{html.escape(JOB["log"])}</div></body></html>"""
            body = result_html.encode("utf-8")
            self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/favicon.png":
            if not FAVICON_PATH.exists():
                self.send_error(404)
                return
            body = FAVICON_PATH.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/":
            body = FORM_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/status":
            self.do_status()
            return
        if self.path == "/result":
            self.do_result()
            return
        self.send_error(404)
    def log_message(self, format_str, *args):
        return


def main():
    setup_file_logging()
    selected_port = pick_free_port(HOST, PORT, max_tries=30)
    os.environ["WOW_UI_URL"] = f"http://{HOST}:{selected_port}/"
    server = ThreadingHTTPServer((HOST, selected_port), Handler)
    SERVER_REF["server"] = server

    url = f"http://{HOST}:{selected_port}/"
    print(f"UI запущен: {url}")
    logging.info("UI server started at %s", url)
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    try:
        if run_task_mode_if_requested():
            sys.exit(0)
        main()
    except Exception:
        logging.exception("Fatal error in app_ui")
        raise
