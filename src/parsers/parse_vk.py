import json
import html
import os
import re
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime


API_URL = "https://api.vk.ru/method/execute"
API_VERSION = "5.275"
CLIENT_ID = "6287487"

ACCESS_TOKEN = os.getenv("VK_ACCESS_TOKEN", "")

INPUT_FILE = "vk_clips.txt"
OUTPUT_JSON = "result.json"
OUTPUT_HTML = "index.html"

DELAY_SECONDS = 0.35
OWNER_DELAY_SECONDS = 0.12
MAX_RETRIES = 4


def extract_raw_id(line: str) -> str | None:
    match = re.search(r"clip(-?\d+_\d+)", line)
    if match:
        return match.group(1)

    match = re.search(r"(-?\d+_\d+)", line)
    if match:
        return match.group(1)

    return None


def build_video_url(raw_id: str) -> str:
    return f"https://vk.ru/clip{raw_id}"


def vk_post(method_url: str, payload: dict) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(method_url, data=payload, timeout=40)
            data = response.json()

            if "error" in data:
                error_code = data["error"].get("error_code")
                error_msg = data["error"].get("error_msg")

                if error_code in (6, 9, 10, 29, 429):
                    sleep_time = DELAY_SECONDS * attempt * 2
                    print(f"[THROTTLE] {error_code}: {error_msg}. Sleep {sleep_time}s")
                    time.sleep(sleep_time)
                    continue

                raise RuntimeError(data["error"])

            return data

        except Exception as e:
            if attempt == MAX_RETRIES:
                raise

            sleep_time = DELAY_SECONDS * attempt * 2
            print(f"[RETRY] {e}. Sleep {sleep_time}s")
            time.sleep(sleep_time)

    return {}


def vk_get(method: str, params: dict) -> dict:
    url = f"https://api.vk.ru/method/{method}"

    params = {
        **params,
        "access_token": ACCESS_TOKEN,
        "v": API_VERSION,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()

            if "error" in data:
                error_code = data["error"].get("error_code")
                error_msg = data["error"].get("error_msg")

                if error_code in (6, 9, 10, 29, 429):
                    sleep_time = OWNER_DELAY_SECONDS * attempt * 2
                    print(f"[OWNER THROTTLE] {error_code}: {error_msg}. Sleep {sleep_time}s")
                    time.sleep(sleep_time)
                    continue

                raise RuntimeError(data["error"])

            return data

        except Exception as e:
            if attempt == MAX_RETRIES:
                raise

            sleep_time = OWNER_DELAY_SECONDS * attempt * 2
            print(f"[OWNER RETRY] {e}. Sleep {sleep_time}s")
            time.sleep(sleep_time)

    return {}


def get_clip(raw_id: str) -> dict:
    code = f'''
    return [
      API.shortVideo.getRecom({{
        "ref":"clips",
        "fields":"photo_50,photo_100,photo_200,photo_400,is_nft,about,description,followers_count,is_closed,verified,screen_name,friend_status,is_subscribed,blacklisted,domain,sex,can_write_private_message,first_name_gen,last_name_gen,first_name_acc,is_service_account,is_nft_photo,trust_mark,admin_level,member_status,members_count,is_member,ban_info,can_message,video_lives_data",
        "count":10
      }}),
      API.shortVideo.get({{
        "short_video_raw_ids":"{raw_id}",
        "fields":"photo_50,photo_100,photo_200,photo_400,is_nft,about,description,followers_count,is_closed,verified,screen_name,friend_status,is_subscribed,blacklisted,domain,sex,can_write_private_message,first_name_gen,last_name_gen,first_name_acc,is_service_account,is_nft_photo,trust_mark,admin_level,member_status,members_count,is_member,ban_info,can_message,video_lives_data"
      }})
    ];
    '''

    payload = {
        "v": API_VERSION,
        "client_id": CLIENT_ID,
        "access_token": ACCESS_TOKEN,
        "code": code,
    }

    return vk_post(API_URL, payload)


def get_owner_info(owner_id: int, cache: dict) -> dict:
    if owner_id in cache:
        return cache[owner_id]

    try:
        if owner_id > 0:
            data = vk_get("users.get", {
                "user_ids": owner_id,
                "fields": "screen_name,photo_100,followers_count"
            })

            user = data["response"][0]

            owner = {
                "owner_id": owner_id,
                "owner_type": "user",
                "owner_name": f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                "owner_screen_name": user.get("screen_name", ""),
                "owner_photo": user.get("photo_100", ""),
                "owner_followers": user.get("followers_count", 0),
                "owner_url": f"https://vk.ru/id{owner_id}",
            }

        else:
            data = vk_get("groups.getById", {
                "group_ids": abs(owner_id),
                "fields": "screen_name,photo_100,members_count"
            })

            groups = data.get("response", {}).get("groups") or data.get("response", [])
            group = groups[0]

            screen_name = group.get("screen_name", "")

            owner = {
                "owner_id": owner_id,
                "owner_type": "group",
                "owner_name": group.get("name", ""),
                "owner_screen_name": screen_name,
                "owner_photo": group.get("photo_100", ""),
                "owner_followers": group.get("members_count", 0),
                "owner_url": f"https://vk.ru/{screen_name}" if screen_name else f"https://vk.ru/club{abs(owner_id)}",
            }

    except Exception as e:
        print(f"[OWNER ERROR] {owner_id}: {e}")

        owner = {
            "owner_id": owner_id,
            "owner_type": "unknown",
            "owner_name": "Unknown",
            "owner_screen_name": "",
            "owner_photo": "",
            "owner_followers": 0,
            "owner_url": f"https://vk.ru/id{owner_id}" if owner_id > 0 else f"https://vk.ru/club{abs(owner_id)}",
        }

    cache[owner_id] = owner
    time.sleep(OWNER_DELAY_SECONDS)

    return owner


def extract_item(api_response: dict) -> dict:
    try:
        return api_response["response"][1]["feed"]["items"][0]["item"]
    except Exception:
        return {}


def parse_clip(api_response: dict, raw_id: str, original_url: str, owner_cache: dict) -> dict:
    item = extract_item(api_response)

    raw_owner_id = int(raw_id.split("_")[0])

    owner_id = item.get("owner_id") or raw_owner_id
    video_id = item.get("id") or int(raw_id.split("_")[1])

    owner = get_owner_info(int(owner_id), owner_cache)

    timestamp = item.get("publish_timestamp") or item.get("date") or 0

    views = (
        item.get("engagement", {}).get("view_count")
        or item.get("views")
        or item.get("local_views")
        or 0
    )

    publish_date = ""
    if timestamp:
        publish_date = datetime.fromtimestamp(int(timestamp)).strftime("%d.%m.%Y")

    return {
        "raw_id": raw_id,
        "video_id": video_id,
        "owner_id": owner_id,
        "url": original_url or build_video_url(raw_id),

        "owner_type": owner["owner_type"],
        "owner_name": owner["owner_name"],
        "owner_screen_name": owner["owner_screen_name"],
        "owner_photo": owner["owner_photo"],
        "owner_followers": owner["owner_followers"],
        "owner_url": owner["owner_url"],

        "description": item.get("description", ""),
        "publish_timestamp": timestamp,
        "publish_date": publish_date,
        "views": int(views or 0),

        "likes": item.get("likes", {}).get("count", 0),
        "comments": item.get("comments", 0),
        "reposts": item.get("reposts", {}).get("count", 0),
        "title": item.get("title", ""),
    }


def generate_html(rows: list[dict], output_html: str):
    restart_url = os.getenv("WOW_UI_URL", "http://127.0.0.1:8765/")
    total_views = sum(row.get("views", 0) for row in rows)

    authors = {}
    for row in rows:
        key = str(row.get("owner_id"))
        if key not in authors:
            authors[key] = {
                "owner_name": row.get("owner_name", ""),
                "owner_url": row.get("owner_url", ""),
                "owner_photo": row.get("owner_photo", ""),
                "videos": 0,
                "views": 0,
            }

        authors[key]["videos"] += 1
        authors[key]["views"] += row.get("views", 0)

    top_authors = sorted(authors.values(), key=lambda x: x["views"], reverse=True)

    table_rows = []

    for row in rows:
        description = html.escape(row.get("description", "")).replace("\n", "<br>")
        owner_name = html.escape(row.get("owner_name", ""))
        owner_url = html.escape(row.get("owner_url", ""))
        video_url = html.escape(row.get("url", ""))
        owner_photo = html.escape(row.get("owner_photo", ""))

        table_rows.append(f"""
        <tr
          data-views="{row.get('views', 0)}"
          data-owner="{html.escape(str(row.get('owner_id', '')))}"
          data-text="{html.escape((row.get('description', '') + ' ' + row.get('owner_name', '')).lower())}"
        >
          <td>
            <input type="checkbox" class="row-check">
          </td>

          <td>
            <a href="{video_url}" target="_blank">{html.escape(row.get("raw_id", ""))}</a>
          </td>

          <td>
            <div class="owner">
              {'<img src="' + owner_photo + '">' if owner_photo else ''}
              <div>
                <a href="{owner_url}" target="_blank"><b>{owner_name}</b></a>
                <div class="muted">{html.escape(row.get("owner_type", ""))} · ID {row.get("owner_id", "")}</div>
                <div class="muted">Подписчики: {row.get("owner_followers", 0)}</div>
              </div>
            </div>
          </td>

          <td class="description">{description}</td>

          <td data-sort="{row.get('publish_timestamp', 0)}">
            {html.escape(row.get("publish_date", ""))}
          </td>

          <td class="num" data-sort="{row.get('views', 0)}">
            {row.get("views", 0)}
          </td>

          <td class="num" data-sort="{row.get('likes', 0)}">
            {row.get("likes", 0)}
          </td>

          <td class="num" data-sort="{row.get('comments', 0)}">
            {row.get("comments", 0)}
          </td>

          <td class="num" data-sort="{row.get('reposts', 0)}">
            {row.get("reposts", 0)}
          </td>
        </tr>
        """)

    author_cards = []

    for author in top_authors:
        author_cards.append(f"""
        <div class="author-card">
          {'<img src="' + html.escape(author["owner_photo"]) + '">' if author["owner_photo"] else ''}
          <div>
            <a href="{html.escape(author["owner_url"])}" target="_blank">
              <b>{html.escape(author["owner_name"])}</b>
            </a>
            <div class="muted">Видео: {author["videos"]}</div>
            <div class="muted">Просмотры: {author["views"]}</div>
          </div>
        </div>
        """)

    html_content = f"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <link rel="icon" type="image/png" href="favicon.png">
  <title>VK Clips Report PRO</title>

  <style>
    body {{
      font-family: Arial, sans-serif;
      margin: 0;
      background: #f4f6f8;
      color: #1f2937;
    }}

    header {{
      padding: 24px;
      background: #111827;
      color: white;
    }}

    header h1 {{
      margin: 0 0 8px;
    }}

    .container {{
      padding: 24px;
    }}

    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(180px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }}

    .card {{
      background: white;
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 2px 10px rgba(0,0,0,.07);
    }}

    .card .label {{
      color: #6b7280;
      font-size: 13px;
      margin-bottom: 6px;
    }}

    .card .value {{
      font-size: 26px;
      font-weight: 700;
    }}

    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 50;
      display: flex;
      gap: 12px;
      align-items: center;
      background: white;
      padding: 14px;
      border-radius: 14px;
      box-shadow: 0 2px 10px rgba(0,0,0,.08);
      margin-bottom: 20px;
    }}

    input[type="text"] {{
      width: 360px;
      padding: 10px 12px;
      border: 1px solid #d1d5db;
      border-radius: 10px;
      font-size: 14px;
    }}

    button {{
      padding: 10px 14px;
      border: 0;
      border-radius: 10px;
      background: #2563eb;
      color: white;
      cursor: pointer;
      font-weight: 600;
    }}

    button.secondary {{
      background: #374151;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      background: white;
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 2px 10px rgba(0,0,0,.07);
    }}

    th {{
      background: #1f2937;
      color: white;
      padding: 12px;
      text-align: left;
      cursor: pointer;
      font-size: 13px;
      white-space: nowrap;
    }}

    td {{
      padding: 12px;
      border-bottom: 1px solid #e5e7eb;
      vertical-align: top;
      font-size: 14px;
    }}

    tr.selected {{
      background: #eff6ff;
    }}

    tr.hidden {{
      display: none;
    }}

    .owner {{
      display: flex;
      gap: 10px;
      align-items: center;
      min-width: 220px;
    }}

    .owner img,
    .author-card img {{
      width: 42px;
      height: 42px;
      border-radius: 50%;
      object-fit: cover;
    }}

    .description {{
      max-width: 520px;
      line-height: 1.35;
    }}

    .muted {{
      color: #6b7280;
      font-size: 12px;
      margin-top: 3px;
    }}

    .num {{
      text-align: right;
      white-space: nowrap;
      font-weight: 600;
    }}

    a {{
      color: #2563eb;
      text-decoration: none;
    }}

    a:hover {{
      text-decoration: underline;
    }}

    .authors {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
      margin-bottom: 24px;
    }}

    .author-card {{
      background: white;
      padding: 12px;
      border-radius: 14px;
      display: flex;
      gap: 10px;
      align-items: center;
      box-shadow: 0 2px 10px rgba(0,0,0,.06);
    }}

    .section-title {{
      margin: 28px 0 12px;
    }}
  </style>
</head>

<body>

<header>
  <h1>VK Clips Report PRO</h1>
  <div>Автоматический отчет по VK Clips</div>
  <div style="margin-top:10px;"><a href="{html.escape(restart_url)}" style="display:inline-block;padding:8px 12px;border-radius:10px;background:#ffffff;color:#111827;text-decoration:none;font-weight:600;">Парсить заново</a></div>
</header>

<div class="container">

  <div class="stats">
    <div class="card">
      <div class="label">Всего видео</div>
      <div class="value">{len(rows)}</div>
    </div>

    <div class="card">
      <div class="label">Всего просмотров</div>
      <div class="value">{total_views}</div>
    </div>

    <div class="card">
      <div class="label">Авторов</div>
      <div class="value">{len(authors)}</div>
    </div>

    <div class="card">
      <div class="label">Средние просмотры</div>
      <div class="value">{round(total_views / len(rows)) if rows else 0}</div>
    </div>
  </div>

  <div class="toolbar">
    <input id="searchInput" type="text" placeholder="Поиск по автору или описанию">

    <button onclick="selectVisible()">Выбрать видимые</button>
    <button class="secondary" onclick="clearSelection()">Снять выбор</button>

    <div>
      Выбрано: <b id="selectedCount">0</b>
    </div>

    <div>
      Сумма просмотров: <b id="selectedViews">0</b>
    </div>
  </div>

  <h2 class="section-title">Топ авторов</h2>

  <div class="authors">
    {''.join(author_cards)}
  </div>

  <h2 class="section-title">Видео</h2>

  <table id="clipsTable">
    <thead>
      <tr>
        <th></th>
        <th onclick="sortTable(1)">Видео</th>
        <th onclick="sortTable(2)">Автор</th>
        <th onclick="sortTable(3)">Описание</th>
        <th onclick="sortTable(4)">Дата</th>
        <th onclick="sortTable(5)">Просмотры</th>
        <th onclick="sortTable(6)">Лайки</th>
        <th onclick="sortTable(7)">Комментарии</th>
        <th onclick="sortTable(8)">Репосты</th>
      </tr>
    </thead>

    <tbody>
      {''.join(table_rows)}
    </tbody>
  </table>
</div>

<script>
  const checks = document.querySelectorAll('.row-check');
  const searchInput = document.getElementById('searchInput');

  function formatNumber(num) {{
    return String(num);
  }}

  function recalc() {{
    let count = 0;
    let views = 0;

    checks.forEach(check => {{
      const tr = check.closest('tr');

      if (check.checked) {{
        count++;
        views += Number(tr.dataset.views || 0);
        tr.classList.add('selected');
      }} else {{
        tr.classList.remove('selected');
      }}
    }});

    document.getElementById('selectedCount').textContent = formatNumber(count);
    document.getElementById('selectedViews').textContent = formatNumber(views);
  }}

  checks.forEach(check => check.addEventListener('change', recalc));

  searchInput.addEventListener('input', () => {{
    const query = searchInput.value.toLowerCase().trim();

    document.querySelectorAll('#clipsTable tbody tr').forEach(tr => {{
      const text = tr.dataset.text || '';

      if (!query || text.includes(query)) {{
        tr.classList.remove('hidden');
      }} else {{
        tr.classList.add('hidden');
      }}
    }});
  }});

  function selectVisible() {{
    document.querySelectorAll('#clipsTable tbody tr').forEach(tr => {{
      if (!tr.classList.contains('hidden')) {{
        tr.querySelector('.row-check').checked = true;
      }}
    }});

    recalc();
  }}

  function clearSelection() {{
    checks.forEach(check => {{
      check.checked = false;
    }});

    recalc();
  }}

  let sortDirection = {{}};

  function sortTable(columnIndex) {{
    const table = document.getElementById('clipsTable');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));

    sortDirection[columnIndex] = !sortDirection[columnIndex];

    rows.sort((a, b) => {{
      const aCell = a.children[columnIndex];
      const bCell = b.children[columnIndex];

      const aSort = aCell.dataset.sort;
      const bSort = bCell.dataset.sort;

      let aValue = aSort !== undefined ? Number(aSort) : aCell.innerText.trim().toLowerCase();
      let bValue = bSort !== undefined ? Number(bSort) : bCell.innerText.trim().toLowerCase();

      if (aValue < bValue) return sortDirection[columnIndex] ? -1 : 1;
      if (aValue > bValue) return sortDirection[columnIndex] ? 1 : -1;
      return 0;
    }});

    rows.forEach(row => tbody.appendChild(row));
  }}
</script>

</body>
</html>
"""

    Path(output_html).write_text(html_content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="VK clips parser")
    parser.add_argument("--input", default=INPUT_FILE)
    parser.add_argument("--output-json", default=OUTPUT_JSON)
    parser.add_argument("--output-html", default=OUTPUT_HTML)
    args = parser.parse_args()

    global ACCESS_TOKEN
    if not ACCESS_TOKEN and Path("vk_token.txt").exists():
        ACCESS_TOKEN = Path("vk_token.txt").read_text(encoding="utf-8").strip()

    if not ACCESS_TOKEN or ACCESS_TOKEN == "ВСТАВЬ_СЮДА_ACCESS_TOKEN":
        raise RuntimeError("Укажи VK_ACCESS_TOKEN или вставь токен в ACCESS_TOKEN")

    input_path = Path(args.input)

    if not input_path.exists():
        raise FileNotFoundError(f"Не найден файл {args.input}")

    lines = input_path.read_text(encoding="utf-8").splitlines()

    videos = []
    seen = set()

    for line in lines:
        line = line.strip()

        if not line:
            continue

        raw_id = extract_raw_id(line)

        if not raw_id:
            print(f"[SKIP] Не смог достать id из строки: {line}")
            continue

        if raw_id in seen:
            continue

        seen.add(raw_id)

        videos.append({
            "raw_id": raw_id,
            "url": line if line.startswith("http") else build_video_url(raw_id),
        })

    print(f"Найдено видео: {len(videos)}")

    results = []
    owner_cache = {}

    for index, video in enumerate(videos, start=1):
        raw_id = video["raw_id"]

        print(f"[{index}/{len(videos)}] Загружаю {raw_id}")
        print(f"@@PROGRESS {index}/{len(videos)}", flush=True)

        try:
            api_response = get_clip(raw_id)
            parsed = parse_clip(api_response, raw_id, video["url"], owner_cache)
            results.append(parsed)

            print(
                f"  Автор: {parsed['owner_name']} | "
                f"Просмотры: {parsed['views']}"
            )

        except Exception as e:
            print(f"[ERROR] {raw_id}: {e}")

            owner_id = int(raw_id.split("_")[0])

            results.append({
                "raw_id": raw_id,
                "video_id": int(raw_id.split("_")[1]),
                "owner_id": owner_id,
                "url": video["url"],
                "owner_type": "unknown",
                "owner_name": "Unknown",
                "owner_screen_name": "",
                "owner_photo": "",
                "owner_followers": 0,
                "owner_url": build_video_url(raw_id),
                "description": "",
                "publish_timestamp": 0,
                "publish_date": "",
                "views": 0,
                "likes": 0,
                "comments": 0,
                "reposts": 0,
                "title": "",
                "error": str(e),
            })

        time.sleep(DELAY_SECONDS)

    Path(args.output_json).write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    generate_html(results, args.output_html)

    print("")
    print("Готово:")
    print(f"- {args.output_json}")
    print(f"- {args.output_html}")


if __name__ == "__main__":
    main()
