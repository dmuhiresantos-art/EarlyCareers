#!/usr/bin/env python3
"""Envía por Telegram las ofertas nuevas (opcional).
Necesita TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID; si faltan, no hace nada."""
import json
import os
from pathlib import Path

import requests

token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
path = Path(__file__).resolve().parent.parent / "docs" / "new_jobs.json"
if not (token and chat and path.exists()):
    raise SystemExit(0)

jobs = json.loads(path.read_text(encoding="utf-8"))
if not jobs:
    raise SystemExit(0)

lines = [f"[{j['type']}] {j['title']} — {j['company']} ({j['location']})\n{j['url']}" for j in jobs]
chunk, size = [], 0
for line in lines + [None]:
    if line is None or size + len(line) > 3500:
        if chunk:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": f"{len(jobs)} ofertas nuevas\n\n" + "\n\n".join(chunk),
                                "disable_web_page_preview": "true"}, timeout=20)
        chunk, size = [], 0
    if line:
        chunk.append(line)
        size += len(line)
