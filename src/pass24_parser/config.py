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

# ─── Домены-агрегаторы и нерелевантные (пропускать при скрапинге) ─────────────

SKIP_DOMAINS = {
    # Поисковики и агрегаторы
    "avito.ru", "yandex.ru", "yandex.com", "google.com", "google.ru",
    "bing.com", "duckduckgo.com", "mail.ru", "rambler.ru",
    # Соцсети
    "vk.com", "ok.ru", "instagram.com", "facebook.com", "tiktok.com",
    "youtube.com", "dzen.ru", "t.me", "telegram.me",
    # Работа и услуги
    "hh.ru", "headhunter.ru", "superjob.ru", "zoon.ru", "profi.ru", "youdo.com",
    # Отзывы и рейтинги
    "otzovik.com", "irecommend.ru", "flamp.ru", "tripadvisor.ru",
    # Новости и СМИ
    "rbc.ru", "realty.rbc.ru", "kp.ru", "lenta.ru", "ria.ru", "tass.ru",
    "kommersant.ru", "iz.ru", "gazeta.ru", "vedomosti.ru",
    "banki.ru", "forbes.ru", "bfm.ru",
    # Справочники и энциклопедии
    "wikipedia.org", "wiktionary.org", "dic.academic.ru", "kartaslov.ru",
    "gramota.ru", "consultant.ru", "garant.ru",
    # Финансы и банки
    "alfabank.ru", "kurs.alfabank.ru", "sberbank.ru", "tinkoff.ru",
    # Недвижимость (агрегаторы, не сайты КП)
    "cian.ru", "domclick.ru", "restate.ru", "novostroy.ru", "mirkvartir.ru",
    "domofond.ru", "m2.ru", "etagi.com", "emls.ru",
    # Юридические и бизнес-порталы
    "law.ru", "klerk.ru", "buh.ru", "nalog.ru",
    # Технические/IT
    "habr.com", "vc.ru", "pikabu.ru", "geekbrains.ru",
    # Международные (DDG иногда уводит)
    "t-online.de", "telekom.de", "theplanetsworld.com", "tripzaza.com",
    "usnews.com", "infotour.ro", "guias-viajar.com",
    # Украинские ТВ (DDG путает "ТСН" с телеканалом)
    "tsn.ua", "1plus1.ua", "1plus1.video", "liveam.tv",
    # Бизнес-реестры и банки (контакты из реестров — не контакты КП)
    "audit-it.ru", "vbankcenter.ru", "tbank.ru", "rusprofile.ru",
    "list-org.com", "sbis.ru", "checko.ru", "egrul.nalog.ru",
    # Украинские сайты (DDG путает ТСН/ТСН-канал)
    "24tv.ua", "tsn24.ru",
    # Информационные порталы (не сайты КП)
    "sntclub.ru", "4tsg.ru", "pandia.ru", "pandia.org",
    "kutuzovskij.ru", "kpmedia.ru",
    # Сервисные компании (не сами КП)
    "spezremont.ru", "artstory-design.com", "serviceuk.ru",
    # Каталоги недвижимости (дополнение)
    "cottage.ru", "kottedzhnye-poselki-podmoskovya.ru",
    "poselkimoskvy.ru", "domzamkad.ru", "peresvetovo1.ru",
    "kf.expert", "gectaro.com", "rating.gd.ru",
    # Агентства недвижимости (продают участки, не управляют КП)
    "slrealty.ru", "choice-estate.ru", "ydacha.ru", "sit-company.ru",
    "novostroy-m.ru", "omhome.ru", "move.ru", "rublevka-road.ru",
    "poselki.ru", "poseloklife.ru",
    # Обслуживающие компании (не сами КП)
    "tehnic-servis.ru", "appes.ru", "life-service.info",
    # Прочие нерелевантные
    "okdesk.ru", "snrd.ru", "avadom.ru",
    "finance.rambler.ru", "sanstv.ru", "slova-znachenie.ru",
    "remontka.pro", "businesscommandos.ru", "sky.pro", "skypro.ru",
    "gtmarket.ru", "investfuture.ru", "gogov.ru", "fssp.gov.ru",
}

# ─── Ключевые слова релевантности КП ────────────────────────────────────────
# Результат считается релевантным, если содержит ХОТЯ БЫ ОДНО слово из PRIMARY
# ИЛИ содержит два и более слов из SECONDARY (одно secondary = нерелевантно)

KP_RELEVANCE_PRIMARY = {
    "коттеджный поселок", "коттеджный посёлок", "коттеджного поселка",
    "коттеджных поселков", "коттеджном поселке",
    " кп ", "днп ",
}

KP_RELEVANCE_SECONDARY = {
    "тсн", "снт", "тсж",
    "поселок", "посёлок", "поселка",
    "председател", "правлени",
    "управляющ", "управление поселк",
    "пропуск", "шлагбаум", "кпп", "охран",
}

# Антислова — если есть, результат точно нерелевантный
KP_RELEVANCE_BLACKLIST = {
    "новости тсн", "tsn.ua", "1plus1", "1+1", "24 канал", "24tv",
    "windows", "computer", "python", "javascript",
    "мвд", "фссп", "суд ", "прокуратур",
    "курс", "обучен", "tutorial",
    "boston", "travel", "hotel", "tourism",
    "t-online", "telekom",
    # Сервисные/консалтинговые
    "юридическ", "бухгалтер", "аудит",
    "ремонт квартир", "дизайн интерьер",
    # Каталоги и рейтинги КП (не сами КП)
    "рейтинг коттеджных", "лучших коттеджных", "топ коттеджных",
    "обзор коттеджных", "каталог коттеджных",
    # Информационные статьи
    "как создать тсн", "как зарегистрировать", "регистрация тсн",
    "что такое тсн", "что такое снт",
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
