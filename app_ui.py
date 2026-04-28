#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import html
import io
import json
import socket
import sys
import threading
import time
import traceback
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import unified_app


HOST = "127.0.0.1"
PORT = 8765
IDLE_TIMEOUT_SEC = 120

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
    },
}
LAST_HEARTBEAT_TS = time.monotonic()
SERVER_REF = {"server": None}


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
.row { display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px; }
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
    <label>URLs (по одной ссылке в строке):</label><br>
    <textarea name="urls"></textarea>
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
    <label><input type="checkbox" name="skip_dzen"> Пропустить Dzen</label>
  </div>
  <button type="submit">Запустить парсинг</button>
  <button type="button" id="stopAppBtn" style="margin-left:8px;background:#fee2e2;border:1px solid #fecaca;">Остановить приложение</button>
</form>
<div id="waitBox" class="wait">
  <b>Пожалуйста, подождите, идет парсинг...</b>
  <div class="bar-wrap"><div class="row"><span>Общий прогресс</span><span id="gVal">0%</span></div><div class="bar"><div id="gBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>WOW fetch</span><span id="wowVal">0%</span></div><div class="bar"><div id="wowBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>Splitter</span><span id="splitterVal">0%</span></div><div class="bar"><div id="splitterBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>VK</span><span id="vkVal">0%</span></div><div class="bar"><div id="vkBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>TikTok</span><span id="tiktokVal">0%</span></div><div class="bar"><div id="tiktokBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>YouTube</span><span id="youtubeVal">0%</span></div><div class="bar"><div id="youtubeBar" class="bar-fill"></div></div></div>
  <div class="bar-wrap"><div class="row"><span>Dzen</span><span id="dzenVal">0%</span></div><div class="bar"><div id="dzenBar" class="bar-fill"></div></div></div>
</div>
<script>
const form = document.querySelector('form');
const waitBox = document.getElementById('waitBox');
let timer = null;
let heartbeatTimer = null;

function setBar(id, value) {
  const v = Math.max(0, Math.min(100, Number(value || 0)));
  document.getElementById(id + 'Bar').style.width = v + '%';
  document.getElementById(id + 'Val').textContent = v + '%';
}

async function pollStatus() {
  const r = await fetch('/status');
  const s = await r.json();
  setBar('g', s.progress.global);
  setBar('wow', s.progress.wow);
  setBar('splitter', s.progress.splitter);
  setBar('vk', s.progress.vk);
  setBar('tiktok', s.progress.tiktok);
  setBar('youtube', s.progress.youtube);
  setBar('dzen', s.progress.dzen);
  if (!s.running) {
    clearInterval(timer);
    timer = null;
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

async function sendHeartbeat() {
  try { await fetch('/heartbeat', { method: 'POST' }); } catch (e) {}
}

document.getElementById('stopAppBtn').addEventListener('click', async () => {
  const ok = confirm('Закрыть приложение?');
  if (!ok) return;
  try {
    await fetch('/shutdown', { method: 'POST' });
  } catch (e) {}
  document.body.innerHTML = '<h2 style="font-family:Arial,sans-serif">Приложение остановлено. Можно закрыть вкладку.</h2>';
});

heartbeatTimer = setInterval(sendHeartbeat, 15000);
sendHeartbeat();
window.addEventListener('beforeunload', () => {
  try { navigator.sendBeacon('/heartbeat'); } catch (e) {}
});
</script>
</div>
</body>
</html>"""


def run_pipeline(form):
    mode = (form.get("mode", ["urls"])[0] or "urls").strip()
    vk_token = (form.get("vk_token", [""])[0] or "").strip()
    urls = (form.get("urls", [""])[0] or "").strip()
    wow_data = (form.get("wow_data", [""])[0] or "").strip()

    if mode == "urls" and not urls:
        raise RuntimeError("В режиме URLs нужно заполнить поле URLs.")
    if mode == "wow" and not wow_data:
        raise RuntimeError("В режиме WOW API нужно заполнить поле wowData.")

    if vk_token:
        Path("vk_token.txt").write_text(vk_token + "\n", encoding="utf-8")
    if urls:
        Path("urls.txt").write_text(urls + "\n", encoding="utf-8")
    if wow_data:
        Path("wowData.txt").write_text(wow_data + "\n", encoding="utf-8")

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
        global LAST_HEARTBEAT_TS

        if self.path == "/heartbeat":
            LAST_HEARTBEAT_TS = time.monotonic()
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

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
            for k in JOB["progress"]:
                JOB["progress"][k] = 0

            old_argv = sys.argv[:]
            buffer = io.StringIO()
            writer = io.StringIO()

            def on_progress(stage, value):
                if stage in JOB["progress"]:
                    JOB["progress"][stage] = max(JOB["progress"][stage], int(value))

            try:
                mode = (form.get("mode", ["urls"])[0] or "urls").strip()
                vk_token = (form.get("vk_token", [""])[0] or "").strip()
                urls = (form.get("urls", [""])[0] or "").strip()
                wow_data = (form.get("wow_data", [""])[0] or "").strip()

                if mode == "urls" and not urls:
                    raise RuntimeError("В режиме URLs нужно заполнить поле URLs.")
                if mode == "wow" and not wow_data:
                    raise RuntimeError("В режиме WOW API нужно заполнить поле wowData.")

                if vk_token:
                    Path("vk_token.txt").write_text(vk_token + "\n", encoding="utf-8")
                if urls:
                    Path("urls.txt").write_text(urls + "\n", encoding="utf-8")
                if wow_data:
                    Path("wowData.txt").write_text(wow_data + "\n", encoding="utf-8")

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
            {"running": JOB["running"], "done": JOB["done"], "error": JOB["error"], "progress": JOB["progress"]},
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
            <h2>Ошибка</h2><p><a href="/">Назад к форме</a></p>
            <h3>Лог</h3><div class="log">{html.escape(JOB["log"])}</div>
            <h3>Трассировка</h3><div class="log">{html.escape(JOB["error"])}</div></body></html>"""
            body = result_html.encode("utf-8")
            self.send_response(500)
        else:
            result_html = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><title>Результат</title>
            <body style="font-family:Arial,sans-serif;margin:20px;background:#f4f7fb">
            <h2>Готово</h2>
            <p>Сформированы файлы <code>report.html</code> и <code>report.json</code>.</p>
            <p><a href="/">Назад к форме</a></p>
            <h3>Лог</h3><div class="log">{html.escape(JOB["log"])}</div></body></html>"""
            body = result_html.encode("utf-8")
            self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
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
    selected_port = pick_free_port(HOST, PORT, max_tries=30)
    server = ThreadingHTTPServer((HOST, selected_port), Handler)
    SERVER_REF["server"] = server

    def idle_shutdown_watcher():
        while True:
            time.sleep(5)
            if JOB["running"]:
                continue
            if time.monotonic() - LAST_HEARTBEAT_TS > IDLE_TIMEOUT_SEC:
                try:
                    server.shutdown()
                except Exception:
                    pass
                break

    threading.Thread(target=idle_shutdown_watcher, daemon=True).start()

    url = f"http://{HOST}:{selected_port}/"
    print(f"UI запущен: {url}")
    webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
