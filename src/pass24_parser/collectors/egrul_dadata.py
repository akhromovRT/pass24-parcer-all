"""ЕГРЮЛ коллектор — поиск ТСН/СНТ/ДНП МО через dadata.ru API.

Для каждой организации извлекает официальные данные реестра:
  - ФИО и должность руководителя (management.name / management.post)
  - ИНН, ОГРН, юридический адрес
  - Телефоны и email (если dadata предоставляет на текущем тарифе)

Env: DADATA_API_KEY
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import ssl
import time
import urllib.request
from typing import Optional

from pass24_parser.collectors.base import BaseCollector
from pass24_parser.models import CollectorResult, ObjectType, ParsedContact
from pass24_parser.storage import Storage

logger = logging.getLogger(__name__)

_SUGGEST_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party"
_ssl_ctx = ssl.create_default_context()

_MO_KEYWORDS = ("московская обл", "московская область", "г москва", "москва,")

_SKIP_STATUSES = {"LIQUIDATED", "LIQUIDATING", "BANKRUPT"}

# Запросы и роль по умолчанию если management.post пустой
_QUERIES: list[tuple[str, str]] = [
    ("товарищество собственников недвижимости", "Председатель правления"),
    ("ТСН коттеджный поселок", "Председатель правления"),
    ("садовое некоммерческое товарищество", "Председатель"),
    ("дачное некоммерческое партнерство", "Председатель"),
    ("некоммерческое партнерство поселок", "Директор"),
]


def _suggest_party(
    query: str,
    api_key: str,
    *,
    offset: int = 0,
    retries: int = 3,
) -> list[dict]:
    """Синхронный вызов dadata suggest/party с повторными попытками."""
    payload = json.dumps({
        "query": query,
        "count": 20,
        "offset": offset,
        "locations": [
            {"region": "московская область"},
            {"region": "москва"},
        ],
        "filters": [{"type": "LEGAL"}],
    }).encode()
    req = urllib.request.Request(
        _SUGGEST_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Token {api_key}",
        },
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20, context=_ssl_ctx) as r:
                return json.loads(r.read()).get("suggestions", [])
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def _is_mo(item: dict) -> bool:
    """Проверяет, что организация в МО или Москве."""
    data = item.get("data") or {}
    addr = data.get("address") or {}
    value = (addr.get("value") or "").lower()
    addr_data = addr.get("data") or {}
    region = (addr_data.get("region_with_type") or "").lower()
    return any(kw in value or kw in region for kw in _MO_KEYWORDS)


def _region_label(address: str) -> str:
    low = address.lower()
    if "г москва" in low or low.startswith("москва,") or low.startswith("москва "):
        return "Москва"
    return "Московская область"


def _parse_suggestion(item: dict, default_role: str) -> Optional[ParsedContact]:
    data = item.get("data") or {}

    status = (data.get("state") or {}).get("status", "")
    if status in _SKIP_STATUSES:
        return None

    inn = data.get("inn", "")
    if not inn:
        return None

    name_block = data.get("name") or {}
    org_name = (
        name_block.get("short_with_opf")
        or name_block.get("full_with_opf")
        or item.get("value", "")
    )

    mgmt = data.get("management") or {}
    raw_name = mgmt.get("name") or ""
    contact_name = raw_name.title() if raw_name else None  # "ИВАНОВ ИВАН" → "Иванов Иван"
    contact_role = mgmt.get("post") or default_role or None

    addr_block = data.get("address") or {}
    address = addr_block.get("value", "")

    # Телефоны/email — доступны на некоторых тарифах dadata
    phones: list[dict] = data.get("phones") or []
    emails: list[dict] = data.get("emails") or []
    contact_phone = phones[0].get("value") if phones else None
    contact_email = emails[0].get("value") if emails else None

    return ParsedContact(
        object_name=org_name,
        object_type=ObjectType.KP,
        object_address=address,
        object_region=_region_label(address),
        contact_name=contact_name,
        contact_role=contact_role,
        contact_phone=contact_phone,
        contact_email=contact_email,
        org_name=org_name,
        org_inn=inn,
        org_ogrn=data.get("ogrn") or None,
        sources=[f"egrul_dadata:{inn}"],
    )


class EgrulDadataCollector(BaseCollector):
    """Коллектор ТСН/СНТ/ДНП МО из dadata.ru (ЕГРЮЛ).

    Возвращает ParsedContact с официальным ФИО руководителя, ИНН, ОГРН и адресом.
    Дедупликация по ИНН через таблицу processed_urls (ключ = "dadata:{inn}").
    """

    name = "egrul_dadata"

    def __init__(self, max_per_query: int = 500, skip_processed: bool = True):
        self.api_key = os.getenv("DADATA_API_KEY", "")
        self.max_per_query = max_per_query
        self.skip_processed = skip_processed

    async def collect(self, region: str = "moscow_oblast", **kwargs) -> CollectorResult:
        if not self.api_key:
            return CollectorResult(
                source=self.name,
                contacts=[],
                errors=["DADATA_API_KEY не задан в .env"],
            )

        all_contacts: list[ParsedContact] = []
        errors: list[str] = []
        seen_inns: set[str] = set()  # дедупликация внутри текущего прогона

        storage = Storage() if self.skip_processed else None

        for query_text, default_role in _QUERIES:
            print(f"\n  [dadata] '{query_text}'")
            query_new = 0
            offset = 0

            while offset < self.max_per_query:
                try:
                    suggestions = await asyncio.to_thread(
                        _suggest_party, query_text, self.api_key, offset=offset
                    )
                except Exception as exc:
                    errors.append(f"dadata '{query_text}' offset={offset}: {exc}")
                    logger.error("[dadata] Ошибка при запросе: %s", exc)
                    break

                if not suggestions:
                    break

                for item in suggestions:
                    if not _is_mo(item):
                        continue

                    contact = _parse_suggestion(item, default_role)
                    if contact is None:
                        continue

                    inn = contact.org_inn or ""
                    if inn in seen_inns:
                        continue

                    # Пропускаем ИНН, уже обработанные в прошлых прогонах
                    inn_key = f"dadata:{inn}"
                    if storage and storage.is_url_processed(inn_key):
                        continue

                    seen_inns.add(inn)
                    all_contacts.append(contact)
                    query_new += 1

                    if storage:
                        storage.mark_url_processed(inn_key, source=self.name)

                offset += len(suggestions)
                if len(suggestions) < 20:
                    break

                await asyncio.sleep(0.12)  # ~8 запросов/сек, лимит dadata = 10

            print(f"    → {query_new} новых организаций")

        if storage:
            storage.close()

        logger.info("[dadata] Итого: %d контактов", len(all_contacts))
        return CollectorResult(source=self.name, contacts=all_contacts, errors=errors)
