"""Дедупликация контактов.

Приоритет ключей дедупликации (из pipeline.md):
1. ИНН организации (самый надёжный)
2. Email ЛПР
3. Телефон ЛПР
4. Название объекта + адрес (fuzzy)

При слиянии: данные из более надёжного источника имеют приоритет
(ЕГРЮЛ > сайт > 2GIS > карты).
"""

from __future__ import annotations

import logging
from typing import Optional

from pass24_parser.models import ParsedContact

logger = logging.getLogger(__name__)

SOURCE_PRIORITY = {
    "egrul": 0,
    "website": 1,
    "2gis": 2,
    "yandex_maps": 3,
}


def _source_rank(contact: ParsedContact) -> int:
    """Возвращает приоритет источника (меньше = надёжнее)."""
    for source in contact.sources:
        if source in SOURCE_PRIORITY:
            return SOURCE_PRIORITY[source]
    return 99


def _merge_contacts(existing: ParsedContact, new: ParsedContact) -> ParsedContact:
    """Сливает два контакта, приоритет у более надёжного источника."""
    if _source_rank(new) < _source_rank(existing):
        primary, secondary = new, existing
    else:
        primary, secondary = existing, new

    # Заполняем пустые поля primary данными из secondary
    for field in (
        "contact_name", "contact_role", "contact_email", "contact_phone",
        "org_name", "org_inn", "org_ogrn",
        "object_address", "object_region",
    ):
        if not getattr(primary, field) and getattr(secondary, field):
            setattr(primary, field, getattr(secondary, field))

    if primary.object_size is None and secondary.object_size is not None:
        primary.object_size = secondary.object_size
    if primary.has_security is None and secondary.has_security is not None:
        primary.has_security = secondary.has_security
    if primary.has_skud is None and secondary.has_skud is not None:
        primary.has_skud = secondary.has_skud

    # Объединяем источники
    for src in secondary.sources:
        if src not in primary.sources:
            primary.sources.append(src)

    return primary


def _normalize_for_fuzzy(text: str) -> str:
    """Нормализует текст для нечёткого сравнения."""
    import re

    text = text.lower().strip()
    text = re.sub(r"[«»\"'().,;:!?—–-]", " ", text)
    text = re.sub(r"\s+", " ", text)
    # Убираем распространённые префиксы
    for prefix in ("кп ", "жк ", "бц ", "тсн ", "снт ", "ук "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.strip()


def deduplicate(contacts: list[ParsedContact]) -> list[ParsedContact]:
    """Дедупликация списка контактов с приоритетным слиянием.

    Возвращает список уникальных контактов.
    """
    # Индексы для быстрого поиска дубликатов
    by_inn: dict[str, int] = {}
    by_email: dict[str, int] = {}
    by_phone: dict[str, int] = {}
    by_name_addr: dict[str, int] = {}

    result: list[ParsedContact] = []

    for contact in contacts:
        merged_idx: Optional[int] = None

        # 1. По ИНН
        if contact.org_inn:
            if contact.org_inn in by_inn:
                merged_idx = by_inn[contact.org_inn]

        # 2. По email
        if merged_idx is None and contact.contact_email:
            email = contact.contact_email.lower()
            if email in by_email:
                merged_idx = by_email[email]

        # 3. По телефону
        if merged_idx is None and contact.contact_phone:
            if contact.contact_phone in by_phone:
                merged_idx = by_phone[contact.contact_phone]

        # 4. По названию + адрес (fuzzy)
        if merged_idx is None and contact.object_name:
            key = _normalize_for_fuzzy(contact.object_name + " " + contact.object_address)
            if key in by_name_addr:
                merged_idx = by_name_addr[key]

        if merged_idx is not None:
            # Сливаем с существующим
            result[merged_idx] = _merge_contacts(result[merged_idx], contact)
            logger.debug("Дубль слит: %s", contact.object_name)
        else:
            # Новый уникальный контакт
            idx = len(result)
            result.append(contact)

            if contact.org_inn:
                by_inn[contact.org_inn] = idx
            if contact.contact_email:
                by_email[contact.contact_email.lower()] = idx
            if contact.contact_phone:
                by_phone[contact.contact_phone] = idx
            if contact.object_name:
                key = _normalize_for_fuzzy(contact.object_name + " " + contact.object_address)
                by_name_addr[key] = idx

    logger.info(
        "Дедупликация: %d → %d контактов", len(contacts), len(result)
    )
    return result
