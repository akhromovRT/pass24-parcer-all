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


async def enrich_contact(contact: ParsedContact) -> ParsedContact:
    """Главная функция обогащения — запускает все доступные обогатители."""
    # ЕГРЮЛ — если есть ИНН/ОГРН или название организации
    if contact.org_inn or contact.org_ogrn or contact.org_name:
        contact = await enrich_from_egrul(contact)

    return contact
