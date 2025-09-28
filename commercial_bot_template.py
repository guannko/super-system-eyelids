#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Commercial Telegram Bot Template (Sellable)

Goals:
- Easy to customize for each client
- No external heavy frameworks (uses standard library only)
- Lead capture (stores leads to CSV)
- Clear pricing presentation: $299 / $599 / $999
- Ready to run with a single token

How to use:
1) Set TELEGRAM_BOT_TOKEN as environment variable or in .env file alongside this script:
   TELEGRAM_BOT_TOKEN=123456:ABC...
2) Run: python3 commercial_bot_template.py
3) Customize TEXTS, KEYWORDS, MENU, and FAQ below per client.

What you can sell instantly:
- Basic plan ($299): greeting, help, FAQ
- Pro plan ($599): keyword routing, simple menu, lead capture to CSV
- Elite plan ($999): promo broadcasts (send to file-based subscriber list)

Note: This template keeps things intentionally simple to speed up delivery and reduce support.
"""

import os
import time
import json
import csv
import logging
from logging.handlers import RotatingFileHandler
from urllib import request, parse
from typing import Optional, Dict, Any

# ===================== SIMPLE CONFIG (PER CLIENT) =====================
BOT_NAME = "Acme Assistant"
COMPANY_NAME = "Acme Corp"

TEXTS = {
    "greeting": f"Здравствуйте! Я {BOT_NAME} от {COMPANY_NAME}. Помогу ответить на вопросы и оформить заявку.",
    "help": "Команды:\n/start — начать\n/help — помощь\n/price — тарифы\n/lead — оставить заявку",
    "price": "Наши тарифы для бота:\n- Basic — $299\n- Pro — $599\n- Elite — $999\n\nНапишите /lead чтобы мы связались с вами.",
    "ask_lead": "Оставьте ваш email или телефон. Мы свяжемся в ближайшее время.",
    "thanks": "Спасибо! Заявка сохранена. Мы скоро свяжемся.",
    "unknown": "Не понял запрос. Напишите /help"
}

KEYWORDS = {
    "цена": "price",
    "тариф": "price",
    "стоимость": "price",
    "купить": "price"
}

FAQ = {
    "Какой функционал у бота?": "Ответы на вопросы, сбор лидов, меню, рассылки (Elite).",
    "Как быстро запустить?": "Обычно в течение 24-48 часов после оплаты.",
}

SUBSCRIBERS_FILE = "subscribers.txt"   # one chat_id per line
LEADS_FILE = "leads.csv"               # email/phone, chat_id, ts
LOG_FILE = "bot.log"
POLL_INTERVAL = 2  # seconds

# ===================== LOGGING =====================
logger = logging.getLogger("CommercialBot")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = RotatingFileHandler(LOG_FILE, maxBytes=3*1024*1024, backupCount=2)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(ch)

# ===================== TOKEN LOADING =====================
def load_token() -> Optional[str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    # Try .env in current directory
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path) as f:
                for line in f:
                    if line.strip().startswith("TELEGRAM_BOT_TOKEN="):
                        return line.strip().split("=", 1)[1]
        except Exception:
            pass
    return None

# ===================== TELEGRAM API HELPERS =====================
API_BASE = "https://api.telegram.org/bot{token}/"

def tg_request(token: str, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = API_BASE.format(token=token) + method
    data = parse.urlencode(params).encode()
    req = request.Request(url, data=data)
    with request.urlopen(req, timeout=30) as resp:
        payload = resp.read().decode()
        return json.loads(payload)

# ===================== BOT LOGIC =====================

def send_message(token: str, chat_id: int, text: str):
    try:
        tg_request(token, "sendMessage", {"chat_id": chat_id, "text": text})
    except Exception as e:
        logger.error(f"send_message failed: {e}")


def broadcast(token: str, text: str):
    if not os.path.exists(SUBSCRIBERS_FILE):
        return
    try:
        with open(SUBSCRIBERS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    chat_id = int(line)
                    send_message(token, chat_id, text)
                except Exception:
                    continue
    except Exception as e:
        logger.error(f"broadcast failed: {e}")


def save_lead(contact: str, chat_id: int):
    new_file = not os.path.exists(LEADS_FILE)
    with open(LEADS_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["contact", "chat_id", "ts"])
        writer.writerow([contact, chat_id, int(time.time())])


def ensure_subscriber(chat_id: int):
    try:
        existing = set()
        if os.path.exists(SUBSCRIBERS_FILE):
            with open(SUBSCRIBERS_FILE) as f:
                existing = {x.strip() for x in f if x.strip()}
        if str(chat_id) not in existing:
            with open(SUBSCRIBERS_FILE, "a") as f:
                f.write(str(chat_id) + "\n")
    except Exception as e:
        logger.error(f"ensure_subscriber failed: {e}")


def handle_text(token: str, chat_id: int, text: str, state: Dict[int, str]):
    t = text.strip().lower()

    # lead capture state
    if state.get(chat_id) == "await_lead":
        save_lead(text.strip(), chat_id)
        state.pop(chat_id, None)
        send_message(token, chat_id, TEXTS["thanks"]) 
        ensure_subscriber(chat_id)
        return

    # commands
    if t == "/start":
        send_message(token, chat_id, TEXTS["greeting"]) 
        ensure_subscriber(chat_id)
        return
    if t == "/help":
        send_message(token, chat_id, TEXTS["help"]) 
        return
    if t == "/price":
        send_message(token, chat_id, TEXTS["price"]) 
        return
    if t == "/lead":
        send_message(token, chat_id, TEXTS["ask_lead"]) 
        state[chat_id] = "await_lead"
        return

    # keyword routing
    for kw, action in KEYWORDS.items():
        if kw in t:
            if action == "price":
                send_message(token, chat_id, TEXTS["price"]) 
                return

    # FAQ quick replies
    for q, a in FAQ.items():
        if q.lower() in t:
            send_message(token, chat_id, a)
            return

    send_message(token, chat_id, TEXTS["unknown"]) 


# ===================== POLLING LOOP =====================

def run_bot():
    token = load_token()
    if not token:
        logger.error("Missing TELEGRAM_BOT_TOKEN. Set env var or put it into .env")
        return

    logger.info(f"Starting bot: {BOT_NAME}")

    offset = 0
    state: Dict[int, str] = {}

    while True:
        try:
            updates = tg_request(token, "getUpdates", {"timeout": 25, "offset": offset})
            if updates.get("ok"):
                for upd in updates.get("result", []):
                    offset = max(offset, upd.get("update_id", 0) + 1)
                    msg = upd.get("message") or upd.get("edited_message")
                    if not msg:
                        continue
                    chat_id = msg["chat"]["id"]
                    text = msg.get("text") or ""
                    if text:
                        handle_text(token, chat_id, text, state)
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Bot interrupted by user. Exiting...")
            break
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(3)


if __name__ == "__main__":
    run_bot()
