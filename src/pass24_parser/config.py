"""Конфигурация, константы и regex-паттерны.

Regex-паттерны и HTTP-настройки адаптированы из parser_v3.py.
"""

from __future__ import annotations

import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ─── Пути ────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
DB_PATH = DATA_DIR / "parser.sqlite"

# ─── HTTP ────────────────────────────────────────────────────────────────────

HTTP_TIMEOUT = 18
MAX_RETRY = 3
PAUSE_BETWEEN_REQUESTS = 2.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── Regex-паттерны (из parser_v3) ───────────────────────────────────────────

PHONE_RE = re.compile(
    r"(?:\+7|8)[\s\-]?\(?(\d{3})\)?[\s\-]?(\d{3})[\s\-]?(\d{2})[\s\-]?(\d{2})"
)
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")
VK_RE = re.compile(r"https?://(?:www\.)?vk\.com/([\w.\-]+)")
TG_RE = re.compile(r"https?://(?:www\.)?t(?:elegram)?\.me/([\w.\-]+)")
WA_RE = re.compile(r"https?://(?:wa\.me|api\.whatsapp\.com/send)[/?][\w=&%+]+")

# ─── Домены-агрегаторы (пропускать при скрапинге) ────────────────────────────

SKIP_DOMAINS = {
    "avito.ru",
    "yandex.ru",
    "yandex.com",
    "google.com",
    "google.ru",
    "zoon.ru",
    "profi.ru",
    "youdo.com",
    "vk.com",
    "instagram.com",
    "ok.ru",
    "hh.ru",
    "otzovik.com",
    "irecommend.ru",
    "flamp.ru",
    "wikipedia.org",
    "youtube.com",
    "dzen.ru",
    "mail.ru",
    "bing.com",
    "duckduckgo.com",
    "facebook.com",
    "cian.ru",
    "domclick.ru",
}

# ─── Slug'и контактных страниц ───────────────────────────────────────────────

CONTACT_PAGE_SLUGS = [
    "/contacts",
    "/contact",
    "/kontakty",
    "/kontakt",
    "/about",
    "/o-nas",
    "/o-kompanii",
    "/pravlenie",
    "/rukovodstvo",
    "/management",
]

# ─── Quality Score: веса полей ───────────────────────────────────────────────

QUALITY_WEIGHTS = {
    "contact_email": 0.25,
    "contact_phone": 0.20,
    "contact_name": 0.15,
    "object_size": 0.10,
    "org_inn": 0.10,
    "has_skud": 0.10,
    "has_security": 0.10,
}

QUALITY_EXPORT_THRESHOLD = 0.4
