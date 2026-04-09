"""Seed URL коллектор — скрапинг сайтов КП из готового списка URL.

Самый надёжный коллектор: работает с проверенными URL сайтов КП,
без поискового шума. URL загружаются из файла data/seed_urls.txt.

Формат файла:
  https://example-kp.ru/  # КП Пример
  https://another-kp.ru/  # ТСН Другой посёлок

Пустые строки и строки с # (без URL) игнорируются.
"""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path

from bs4 import BeautifulSoup

from pass24_parser.collectors.base import BaseCollector
from pass24_parser.collectors.website_scraper import (
    extract_contacts_from_html,
    find_contact_page,
    get_domain,
    get_org_name,
    is_skip_domain,
)
from pass24_parser.config import DATA_DIR, PAUSE_BETWEEN_REQUESTS
from pass24_parser.http_client import fetch
from pass24_parser.models import CollectorResult, ObjectType, ParsedContact
from pass24_parser.storage import Storage

logger = logging.getLogger(__name__)

SEED_FILE = DATA_DIR / "seed_urls.txt"


def _load_seed_urls(path: Path = SEED_FILE) -> list[tuple[str, str]]:
    """Загружает URL и комментарии из seed-файла.

    Returns: список (url, comment) кортежей.
    """
    if not path.exists():
        logger.warning("Seed-файл не найден: %s", path)
        return []

    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Разделяем URL и комментарий
        if " # " in line:
            url, comment = line.split(" # ", 1)
        elif "#" in line and not line.startswith("http"):
            continue
        else:
            url, comment = line, ""
        url = url.strip()
        if url.startswith("http"):
            urls.append((url, comment.strip()))
    return urls


def _classify_from_name(name: str) -> ObjectType:
    """Определяет тип объекта по названию."""
    text = name.lower()
    if any(kw in text for kw in ("коттеджн", "кп ", "кп.", "посёлок", "поселок",
                                  "снт", "тсн", "днп", "village")):
        return ObjectType.KP
    if any(kw in text for kw in ("жк ", "жилой комплекс")):
        return ObjectType.ZHK
    return ObjectType.KP  # По умолчанию КП для seed-списка


class SeedUrlCollector(BaseCollector):
    """Коллектор: скрапинг сайтов КП из готового списка URL.

    Читает URL из data/seed_urls.txt, скрапит каждый,
    извлекает контакты, ФИО, email, телефон.
    Пропускает уже обработанные URL (через storage.is_url_processed).
    """

    name = "seed_urls"

    def __init__(self, seed_file: Path = SEED_FILE, skip_processed: bool = True):
        self.seed_file = seed_file
        self.skip_processed = skip_processed

    async def collect(self, region: str = "", **kwargs) -> CollectorResult:
        all_contacts: list[ParsedContact] = []
        errors: list[str] = []

        seed_urls = _load_seed_urls(self.seed_file)
        if not seed_urls:
            logger.warning("Нет URL в seed-файле: %s", self.seed_file)
            return CollectorResult(source=self.name, contacts=[], errors=["Пустой seed-файл"])

        # Фильтр уже обработанных
        storage = Storage() if self.skip_processed else None
        urls_to_process = []
        skipped = 0
        for url, comment in seed_urls:
            if storage and storage.is_url_processed(url):
                skipped += 1
                continue
            if is_skip_domain(url):
                continue
            urls_to_process.append((url, comment))

        if storage:
            storage.close()

        print(f"\n  [Seed] Загружено {len(seed_urls)} URL, пропущено {skipped} обработанных")
        print(f"  [Seed] К обработке: {len(urls_to_process)} сайтов\n")

        for i, (url, comment) in enumerate(urls_to_process, 1):
            print(f"  [{i}/{len(urls_to_process)}] {url[:65]}")

            try:
                resp = await fetch(url)
                if resp is None:
                    print(f"    ✗ Не загрузился")
                    errors.append(f"{url}: не загрузился")
                    continue

                soup = BeautifulSoup(resp.text, "lxml")
                org_name = get_org_name(soup)
                contacts = extract_contacts_from_html(soup, url)

                # Пробуем страницу контактов/правления если нет телефона или ФИО
                if not contacts["phone"] or not contacts.get("contact_name"):
                    contact_url = find_contact_page(url, soup)
                    if contact_url:
                        resp2 = await fetch(contact_url)
                        if resp2:
                            try:
                                soup2 = BeautifulSoup(resp2.text, "lxml")
                                contacts2 = extract_contacts_from_html(soup2, contact_url)
                                for field in ("phone", "email", "address",
                                              "contact_name", "contact_role"):
                                    if not contacts.get(field) and contacts2.get(field):
                                        contacts[field] = contacts2[field]
                            except Exception:
                                pass

                # Имя объекта: из комментария > org_name > домен
                name = comment or org_name or get_domain(url)

                contact = ParsedContact(
                    object_name=name,
                    object_type=_classify_from_name(name),
                    object_address=contacts.get("address", ""),
                    contact_phone=contacts.get("phone", ""),
                    contact_email=contacts.get("email", ""),
                    contact_name=contacts.get("contact_name", ""),
                    contact_role=contacts.get("contact_role", ""),
                    org_name=org_name if org_name != name else "",
                    sources=[url],
                )
                all_contacts.append(contact)

                phone_str = contact.contact_phone or "—"
                email_str = contact.contact_email or "—"
                name_str = contact.contact_name or "—"
                print(f"    ✓ {name[:40]} | ☎ {phone_str} | ✉ {email_str} | 👤 {name_str}")

                # Отмечаем URL как обработанный
                if self.skip_processed:
                    s = Storage()
                    s.mark_url_processed(url, source=self.name)
                    s.close()

            except Exception as e:
                errors.append(f"{url}: {e}")
                print(f"    ✗ Ошибка: {e}")

            await asyncio.sleep(PAUSE_BETWEEN_REQUESTS + random.uniform(0, 0.5))

        return CollectorResult(source=self.name, contacts=all_contacts, errors=errors)
