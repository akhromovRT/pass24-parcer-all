"""Обогатитель данных — ЕГРЮЛ и другие источники.

Дополняет ParsedContact данными из:
- ЕГРЮЛ (nalog.ru): ФИО руководителя по ИНН/ОГРН
- Сайт организации: email, телефон через website_scraper
"""

from __future__ import annotations

import json
import logging

from pass24_parser.http_client import fetch
from pass24_parser.models import ParsedContact

logger = logging.getLogger(__name__)

EGRUL_SEARCH_URL = "https://egrul.nalog.ru/"
EGRUL_RESULT_URL = "https://egrul.nalog.ru/search-result/"


async def enrich_from_egrul(contact: ParsedContact) -> ParsedContact:
    """Обогащает контакт данными из ЕГРЮЛ по ИНН или названию организации.

    ЕГРЮЛ API (egrul.nalog.ru) работает в два этапа:
    1. POST /         — отправить поисковый запрос (ИНН или название)
    2. GET /search-result/{token} — получить результат

    Ограничение: ЕГРЮЛ использует captcha для массовых запросов.
    MVP-реализация работает для единичных запросов.
    """
    query = contact.org_inn or contact.org_name
    if not query:
        return contact

    try:
        # Этап 1: поисковый запрос
        from pass24_parser.http_client import get_client

        client = await get_client()
        resp = await client.post(
            EGRUL_SEARCH_URL,
            data={"query": query},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code != 200:
            logger.warning("ЕГРЮЛ: HTTP %d для запроса '%s'", resp.status_code, query)
            return contact

        data = resp.json()
        token = data.get("t")
        if not token:
            logger.debug("ЕГРЮЛ: нет токена для '%s'", query)
            return contact

        # Этап 2: получение результата
        import asyncio

        await asyncio.sleep(1)  # ЕГРЮЛ требует паузу
        result_resp = await fetch(f"{EGRUL_RESULT_URL}{token}")
        if result_resp is None:
            return contact

        result = result_resp.json()
        rows = result.get("rows", [])
        if not rows:
            return contact

        row = rows[0]  # берём первый результат

        # Извлекаем данные
        if not contact.org_inn:
            contact.org_inn = row.get("i")  # ИНН
        if not contact.org_ogrn:
            contact.org_ogrn = row.get("o")  # ОГРН
        if not contact.org_name:
            contact.org_name = row.get("n")  # Полное название

        # ФИО руководителя (в поле "g" для ИП, "d" для директора)
        director = row.get("d", "")
        if director and not contact.contact_name:
            contact.contact_name = director
            if not contact.contact_role:
                # Определяем роль по типу организации
                org_name_lower = (contact.org_name or "").lower()
                if any(kw in org_name_lower for kw in ("тсн", "снт", "тсж")):
                    contact.contact_role = "Председатель"
                else:
                    contact.contact_role = "Директор"

        if "egrul" not in contact.sources:
            contact.sources.append("egrul")

        logger.info(
            "ЕГРЮЛ: обогащён '%s' — ИНН: %s, руководитель: %s",
            contact.org_name, contact.org_inn, contact.contact_name,
        )

    except Exception as e:
        logger.error("ЕГРЮЛ ошибка для '%s': %s", query, e)

    return contact


async def enrich_from_web(contact: ParsedContact) -> ParsedContact:
    """Ищет телефон/email организации через DDG + скрапинг сайта.

    Для контактов с ФИО+ИНН, но без телефона/email (типично для ЕГРЮЛ/dadata).
    Стратегия:
    1. Быстро: ищет телефон прямо в сниппете DDG (без HTTP-запроса).
    2. Медленно: скрапит найденный URL через website_scraper.
    """
    if contact.contact_phone and contact.contact_email:
        return contact

    org_name = contact.org_name or contact.object_name or ""
    if not org_name:
        return contact

    import asyncio as _asyncio

    from pass24_parser.collectors.ddg_search import _search_ddg
    from pass24_parser.collectors.website_scraper import is_skip_domain, scrape_website
    from pass24_parser.config import PHONE_RE

    city = contact.object_region or "Московская область"
    queries = [
        f'"{org_name}" контакты телефон',
        f'"{org_name}" {city} сайт',
    ]

    found_phone = ""
    found_email = ""
    found_url = ""
    found_name = ""
    found_role = ""

    for query in queries:
        if found_phone and found_email:
            break
        try:
            results = await _asyncio.to_thread(_search_ddg, query, 5)
        except Exception as exc:
            logger.debug("DDG enrich '%s': %s", org_name, exc)
            await _asyncio.sleep(2)
            continue

        for result in results:
            if found_phone:
                break
            url = result.get("url", "")
            desc = result.get("description", "")

            # 1. Телефон из сниппета (без HTTP-запроса)
            if not found_phone and desc:
                m = PHONE_RE.search(desc)
                if m:
                    found_phone = m.group()
                    found_url = found_url or url
                    break

            # 2. Скрапинг сайта
            if url and not is_skip_domain(url):
                try:
                    scraped = await scrape_website(url, org_name)
                    if scraped:
                        if not found_phone and scraped.contact_phone:
                            found_phone = scraped.contact_phone
                            found_url = url
                        if not found_email and scraped.contact_email:
                            found_email = scraped.contact_email
                            found_url = found_url or url
                        if not found_name and scraped.contact_name:
                            found_name = scraped.contact_name
                        if not found_role and scraped.contact_role:
                            found_role = scraped.contact_role
                except Exception as exc:
                    logger.debug("Скрапинг %s: %s", url, exc)

        await _asyncio.sleep(1.5)

    if not found_phone and not found_email:
        return contact

    if found_phone:
        contact.contact_phone = found_phone
    if found_email:
        contact.contact_email = found_email
    if found_name and not contact.contact_name:
        contact.contact_name = found_name
    if found_role and not contact.contact_role:
        contact.contact_role = found_role
    if found_url:
        contact.sources.append(found_url)

    logger.info(
        "Web-обогащение: '%s' → тел: %s  email: %s  сайт: %s",
        org_name,
        found_phone or "—",
        found_email or "—",
        found_url or "—",
    )
    return contact


async def enrich_contact(contact: ParsedContact) -> ParsedContact:
    """Главная функция обогащения — запускает все доступные обогатители."""
    # ЕГРЮЛ — только если есть ИНН или ОГРН; поиск по названию ненадёжен и
    # блокируется с облачных IP (egrul.nalog.ru таймаутится ~18 сек каждый запрос)
    if contact.org_inn or contact.org_ogrn:
        contact = await enrich_from_egrul(contact)

    return contact
