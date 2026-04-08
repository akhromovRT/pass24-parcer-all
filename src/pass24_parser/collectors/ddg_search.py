"""DuckDuckGo коллектор — поиск КП/ТСН через DDG + скрапинг найденных сайтов.

Стратегия поиска основана на ICP из pass24-ai-sales/knowledge/:
- Целевой сегмент: КП Московской области, построенные и заселённые, >30 домов
- ЛПР: председатель правления ТСН/СНТ или представитель УК с правом подписи
- Запросы по районам/шоссе МО + конкретные форматы (ТСН, СНТ, УК)
- Фильтр релевантности: отсекает новостные статьи и справочники
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from urllib.parse import urlparse

from duckduckgo_search import DDGS

from pass24_parser.collectors.base import BaseCollector
from pass24_parser.collectors.website_scraper import (
    extract_contacts_from_html,
    find_contact_page,
    get_domain,
    get_org_name,
    is_skip_domain,
)
from pass24_parser.config import (
    HEADERS,
    KP_RELEVANCE_BLACKLIST,
    KP_RELEVANCE_PRIMARY,
    KP_RELEVANCE_SECONDARY,
    PAUSE_BETWEEN_REQUESTS,
    PHONE_RE,
)
from pass24_parser.http_client import fetch
from pass24_parser.models import CollectorResult, ObjectType, ParsedContact

logger = logging.getLogger(__name__)

# ─── Поисковые запросы ───────────────────────────────────────────────────────
# Основаны на ICP: КП МО, ТСН/СНТ, председатель правления, УК
# Конкретные по районам/шоссе, чтобы DDG возвращал сайты КП, а не статьи

KP_SEARCH_QUERIES: dict[str, list[str]] = {
    # Сайты конкретных КП — самые результативные запросы
    "Сайты КП": [
        'коттеджный поселок официальный сайт контакты правление Подмосковье',
        'коттеджный поселок Новорижское шоссе официальный сайт управляющая компания',
        'коттеджный поселок Рублёвка сайт ТСН контакты телефон',
        'коттеджный поселок Калужское шоссе сайт правление контакты',
        'коттеджный поселок Дмитровское шоссе управление сайт',
        'коттеджный поселок Минское шоссе сайт управляющая компания',
        'коттеджный поселок Киевское шоссе сайт ТСН контакты',
        'коттеджный поселок Ленинградское шоссе сайт правление',
    ],
    # ТСН/СНТ — юридические лица, управляющие КП
    "ТСН и СНТ": [
        'ТСН коттеджный поселок Подмосковье председатель правления контакты сайт',
        'ТСН коттеджный поселок Московская область официальный сайт',
        'СНТ коттеджный поселок Московская область управление сайт',
        'товарищество собственников недвижимости коттеджный поселок МО председатель',
        'ТСН коттеджный поселок Одинцово Истра Красногорск сайт',
        'ТСН поселок председатель правления Подмосковье телефон',
    ],
    # Управляющие компании КП
    "УК поселков": [
        'управляющая компания коттеджного поселка Подмосковье сайт контакты',
        'управление коттеджным поселком МО официальный сайт телефон',
        'обслуживание коттеджного поселка Московская область компания сайт',
    ],
    # Конкретные известные КП по имени (из кейсов PASS24 и рынка)
    "Известные КП": [
        'КП Агаларов Эстейт управление сайт контакты',
        'коттеджный поселок Барвиха официальный сайт управляющая',
        'коттеджный поселок Millennium Park управление сайт',
        'коттеджный поселок Довиль Новорижское управляющая компания',
        'коттеджный поселок Горки-2 управление сайт',
        'коттеджный поселок Жуковка-3 управление контакты',
        'коттеджный поселок Маленькая Италия Новорижское управление',
    ],
    # Бизнес-реестры с ТСН
    "Реестры ТСН": [
        'rusprofile ТСН коттеджный поселок Московская область',
        'список ТСН коттеджных поселков Подмосковье реестр',
        'ЕГРЮЛ ТСН коттеджный поселок Москва область',
    ],
}

SEARCH_LIMIT = 10
PAUSE_DDG = 3.0


def _search_ddg(query: str, limit: int = SEARCH_LIMIT) -> list[dict]:
    """Поиск через DuckDuckGo с retry."""
    results = []
    for attempt in range(1, 4):
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(query, region="ru-ru", max_results=limit):
                    url = r.get("href", "")
                    if url and not is_skip_domain(url):
                        results.append({
                            "url": url,
                            "title": r.get("title", ""),
                            "description": r.get("body", ""),
                        })
            return results
        except Exception as e:
            wait = 5 * attempt
            logger.warning("DDG ошибка (попытка %d/3): %s. Пауза %dс", attempt, e, wait)
            time.sleep(wait)
    return results


def _is_relevant(url: str, title: str, description: str) -> bool:
    """Проверяет релевантность результата.

    Логика:
    1. Blacklist → точно нерелевантно (украинское ТВ, МВД, курсы и т.п.)
    2. Primary keyword → точно релевантно ("коттеджный поселок", "днп")
    3. Домен похож на КП-сайт → релевантно (содержит kp, poselok, cottage, tsn)
    4. Хотя бы 1 secondary keyword → релевантно (поселок, тсн, снт, председатель...)
    5. Иначе → нерелевантно
    """
    text = (url + " " + title + " " + description).lower()
    domain = get_domain(url).lower()

    # 1. Blacklist — точно мимо
    if any(bl in text for bl in KP_RELEVANCE_BLACKLIST):
        return False

    # 2. Primary — точное попадание
    if any(kw in text for kw in KP_RELEVANCE_PRIMARY):
        return True

    # 3. Домен похож на КП-сайт
    kp_domain_hints = ("kp", "poselok", "posyolok", "cottage", "village",
                       "tsn", "snt", "dacha", "selo", "derevn")
    if any(hint in domain for hint in kp_domain_hints):
        return True

    # 4. Хотя бы 1 secondary keyword
    if any(kw in text for kw in KP_RELEVANCE_SECONDARY):
        return True

    return False


def _classify_from_text(title: str, description: str = "") -> ObjectType:
    """Определяет тип объекта по тексту."""
    text = (title + " " + description).lower()
    if any(kw in text for kw in ("коттеджн", "кп ", "посёлок", "поселок", "снт", "тсн", "днп")):
        return ObjectType.KP
    if any(kw in text for kw in ("жк ", "жилой комплекс")):
        return ObjectType.ZHK
    return ObjectType.UNKNOWN


def _extract_region_from_text(text: str) -> str:
    """Извлекает регион/район из текста."""
    text_lower = text.lower()
    districts = [
        "Одинцовский", "Истринский", "Красногорский", "Мытищинский",
        "Наро-Фоминский", "Чеховский", "Подольский", "Солнечногорский",
        "Дмитровский", "Пушкинский", "Щёлковский", "Балашихинский",
        "Ленинский", "Домодедовский", "Раменский", "Люберецкий",
    ]
    for d in districts:
        if d.lower() in text_lower:
            return f"МО, {d} район"

    highways = {
        "новорижск": "Новорижское шоссе",
        "рублёво": "Рублёво-Успенское шоссе",
        "рублево": "Рублёво-Успенское шоссе",
        "калужск": "Калужское шоссе",
        "дмитровск": "Дмитровское шоссе",
        "минск": "Минское шоссе",
        "киевск": "Киевское шоссе",
        "ярославск": "Ярославское шоссе",
        "симферопольск": "Симферопольское шоссе",
        "ленинградск": "Ленинградское шоссе",
    }
    for kw, name in highways.items():
        if kw in text_lower:
            return f"МО, {name}"

    if any(kw in text_lower for kw in ("московск", "подмосков", " мо ")):
        return "Московская область"

    return ""


def _contact_from_meta(item: dict) -> ParsedContact:
    """Создаёт контакт из метаданных поиска (fallback без скрапинга)."""
    title = item.get("title", "").strip()
    desc = item.get("description", "").strip()
    url = item.get("url", "")
    phone_m = PHONE_RE.search(desc)

    return ParsedContact(
        object_name=title[:100],
        object_type=_classify_from_text(title, desc),
        object_region=_extract_region_from_text(title + " " + desc),
        contact_phone=phone_m.group(0) if phone_m else "",
        sources=[url],
    )


class DdgSearchCollector(BaseCollector):
    """Коллектор: DuckDuckGo поиск → скрапинг найденных сайтов КП.

    Запросы основаны на ICP из pass24-ai-sales:
    - По шоссе МО (Новорижское, Рублёво-Успенское, Калужское, ...)
    - По районам МО (Одинцовский, Истринский, Красногорский, ...)
    - По формату управления (ТСН, СНТ, УК)
    - Каталоги КП для извлечения списков

    Фильтр релевантности отсекает новости, статьи, справочники.
    """

    name = "ddg_search"

    def __init__(self, max_results: int = 30, scrape: bool = True):
        self.max_results = max_results
        self.scrape = scrape

    async def collect(self, region: str = "moscow_oblast", **kwargs) -> CollectorResult:
        all_contacts: list[ParsedContact] = []
        errors: list[str] = []
        seen_domains: set[str] = set()

        # Собираем URL через DDG
        print("\n  [DDG] Поиск сайтов КП (ICP-запросы по районам и шоссе МО)...")
        candidate_urls: list[tuple[str, dict]] = []
        filtered_irrelevant = 0

        for category, queries in KP_SEARCH_QUERIES.items():
            print(f"\n    Категория: {category}")
            for query in queries:
                if len(candidate_urls) >= self.max_results * 3:
                    break

                logger.info("DDG: %s", query)
                results = _search_ddg(query, limit=SEARCH_LIMIT)

                relevant_count = 0
                for r in results:
                    domain = get_domain(r["url"])
                    if domain and domain not in seen_domains:
                        # Фильтр релевантности
                        if _is_relevant(r["url"], r["title"], r.get("description", "")):
                            seen_domains.add(domain)
                            candidate_urls.append((r["url"], r))
                            relevant_count += 1
                        else:
                            filtered_irrelevant += 1

                print(f"      → {relevant_count} релевантных из {len(results)} ({query[:55]}...)")
                time.sleep(PAUSE_DDG + random.uniform(0, 1.5))

        print(f"\n  [DDG] Итого: {len(candidate_urls)} релевантных сайтов")
        print(f"  [DDG] Отфильтровано нерелевантных: {filtered_irrelevant}")

        # Ограничиваем до max_results
        candidate_urls = candidate_urls[: self.max_results]

        if not self.scrape:
            for url, meta in candidate_urls:
                all_contacts.append(_contact_from_meta(meta))
            return CollectorResult(source=self.name, contacts=all_contacts, errors=errors)

        # Скрапим сайты
        print(f"\n  [Скрапинг] Обработка {len(candidate_urls)} сайтов...\n")
        from bs4 import BeautifulSoup

        for i, (url, meta) in enumerate(candidate_urls, 1):
            print(f"  [{i}/{len(candidate_urls)}] {url[:70]}")

            try:
                resp = await fetch(url)
                if resp is None:
                    contact = _contact_from_meta(meta)
                    all_contacts.append(contact)
                    print(f"    ✗ Не загрузился → мета: {contact.object_name[:40]}")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                org_name = get_org_name(soup)
                contacts = extract_contacts_from_html(soup, url)

                # Пробуем страницу контактов если нет телефона
                if not contacts["phone"]:
                    contact_url = find_contact_page(url, soup)
                    if contact_url:
                        resp2 = await fetch(contact_url)
                        if resp2:
                            try:
                                soup2 = BeautifulSoup(resp2.text, "lxml")
                                contacts2 = extract_contacts_from_html(soup2, contact_url)
                                for field in ("phone", "email", "address"):
                                    if not contacts[field] and contacts2[field]:
                                        contacts[field] = contacts2[field]
                            except Exception:
                                pass

                title = meta.get("title", "")
                desc = meta.get("description", "")
                name = org_name or title[:100] or get_domain(url)

                contact = ParsedContact(
                    object_name=name,
                    object_type=_classify_from_text(name, desc),
                    object_address=contacts.get("address", ""),
                    object_region=_extract_region_from_text(title + " " + desc + " " + contacts.get("address", "")),
                    contact_phone=contacts.get("phone", ""),
                    contact_email=contacts.get("email", ""),
                    org_name=org_name if org_name != name else "",
                    sources=[url],
                )
                all_contacts.append(contact)

                phone_str = contact.contact_phone or "—"
                email_str = contact.contact_email or "—"
                region_str = contact.object_region or "—"
                print(f"    ✓ {name[:40]} | ☎ {phone_str} | ✉ {email_str} | 📍 {region_str}")

            except Exception as e:
                errors.append(f"{url}: {e}")
                contact = _contact_from_meta(meta)
                all_contacts.append(contact)
                print(f"    ✗ Ошибка: {e}")

            await asyncio.sleep(PAUSE_BETWEEN_REQUESTS + random.uniform(0, 0.5))

        return CollectorResult(source=self.name, contacts=all_contacts, errors=errors)
