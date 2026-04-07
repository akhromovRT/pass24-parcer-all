"""Коллектор 2GIS — основной источник данных для MVP.

Парсит результаты поиска 2GIS по запросам вроде
"коттеджный поселок", "ТСН", "управляющая компания" в целевом регионе.

2GIS предоставляет: название объекта, адрес, телефон, категорию,
рейтинг, часы работы, сайт организации.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from pass24_parser.collectors.base import BaseCollector
from pass24_parser.config import PAUSE_BETWEEN_REQUESTS
from pass24_parser.http_client import fetch
from pass24_parser.models import CollectorResult, ObjectType, ParsedContact

logger = logging.getLogger(__name__)

# Поисковые запросы для 2GIS по типу объекта
TWOGIS_QUERIES: dict[str, list[str]] = {
    "kp": [
        "коттеджный поселок управляющая компания",
        "ТСН коттеджный поселок",
        "СНТ коттеджный поселок",
        "управление коттеджным поселком",
    ],
}

# Маппинг регионов на slug'и 2GIS
REGION_SLUGS = {
    "moscow_oblast": "moscow",
    "spb": "spb",
    "krasnodar": "krasnodar",
}


def _classify_object_type(name: str, categories: str = "") -> ObjectType:
    """Определяет тип объекта по названию и категориям."""
    text = (name + " " + categories).lower()
    if any(kw in text for kw in ("коттеджн", "кп ", "посёлок", "поселок", "снт", "тсн", "днп")):
        return ObjectType.KP
    if any(kw in text for kw in ("жк ", "жилой комплекс", "тсж")):
        return ObjectType.ZHK
    if any(kw in text for kw in ("бизнес-центр", "бц ", "офисн")):
        return ObjectType.BC
    return ObjectType.UNKNOWN


def _parse_org_card(html: str, source_url: str) -> list[ParsedContact]:
    """Парсит HTML страницы результатов 2GIS и извлекает карточки организаций.

    Примечание: 2GIS рендерит контент через JS, поэтому прямой HTML-парсинг
    даёт ограниченные результаты. Для полноценного сбора нужен Playwright
    или 2GIS API. Эта реализация — MVP-заглушка для структурных данных.
    """
    soup = BeautifulSoup(html, "lxml")
    contacts: list[ParsedContact] = []

    # 2GIS рендерит карточки через JS — статический HTML содержит мало данных.
    # Ищем JSON-LD или meta-теги как fallback.
    for script in soup.find_all("script", type="application/ld+json"):
        import json

        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if item.get("@type") not in ("LocalBusiness", "Organization"):
                continue

            name = item.get("name", "")
            if not name:
                continue

            address_obj = item.get("address", {})
            address = address_obj.get("streetAddress", "") if isinstance(address_obj, dict) else ""
            region = address_obj.get("addressRegion", "") if isinstance(address_obj, dict) else ""

            phone = ""
            tel = item.get("telephone", "")
            if isinstance(tel, list):
                phone = tel[0] if tel else ""
            elif isinstance(tel, str):
                phone = tel

            contacts.append(
                ParsedContact(
                    object_name=name,
                    object_type=_classify_object_type(name),
                    object_address=address,
                    object_region=region,
                    contact_phone=phone,
                    org_name=name,
                    sources=[source_url],
                )
            )

    return contacts


class TwoGisCollector(BaseCollector):
    """Коллектор данных из 2GIS.

    MVP-реализация: парсинг HTML-страниц результатов поиска.
    В будущем — интеграция с 2GIS API для более надёжного сбора.
    """

    name = "2gis"

    async def collect(self, region: str = "moscow_oblast", **kwargs) -> CollectorResult:
        slug = REGION_SLUGS.get(region, "moscow")
        queries = TWOGIS_QUERIES.get("kp", [])
        all_contacts: list[ParsedContact] = []
        errors: list[str] = []

        for query in queries:
            url = f"https://2gis.ru/{slug}/search/{quote(query)}"
            logger.info("2GIS: %s", url)

            resp = await fetch(url)
            if resp is None:
                errors.append(f"Не удалось загрузить: {url}")
                continue

            parsed = _parse_org_card(resp.text, url)
            all_contacts.extend(parsed)
            logger.info("2GIS: найдено %d записей для '%s'", len(parsed), query)

            await asyncio.sleep(PAUSE_BETWEEN_REQUESTS)

        return CollectorResult(
            source=self.name,
            contacts=all_contacts,
            errors=errors,
        )
