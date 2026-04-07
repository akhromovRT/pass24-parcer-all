"""Экспорт в Bitrix24 CRM — CSV формат для импорта сделок.

Маппинг полей из pipeline.md (этап 7a).
Формат: "Название сделки,Контакт,Телефон,Email,Компания,Источник,Комментарий"
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from pass24_parser.models import ParsedContact
from pass24_parser.qualifier import calculate_pre_champ_score

logger = logging.getLogger(__name__)


def _build_comment(contact: ParsedContact) -> str:
    """Формирует комментарий к сделке с метаданными для менеджера."""
    parts = []
    if contact.object_type.value != "unknown":
        parts.append(contact.object_type.value.upper())
    if contact.object_size:
        parts.append(f"{contact.object_size} домов")
    if contact.object_region:
        parts.append(contact.object_region)
    if contact.has_security is True:
        parts.append("есть охрана")
    if contact.has_skud is True:
        parts.append("есть СКУД")
    elif contact.has_skud is False:
        parts.append("нет СКУД")

    pre_champ = calculate_pre_champ_score(contact)
    parts.append(f"pre-CHAMP: {pre_champ}")
    parts.append(f"quality: {contact.quality_score:.2f}")

    return ", ".join(parts)


def export_to_csv(contacts: list[ParsedContact], output_path: Path) -> Path:
    """Экспортирует контакты в CSV для импорта в Bitrix24.

    Формат сделки:
    - Название: "{object_name} — подключение PASS24"
    - Воронка: Облако (Cloud SaaS), стадия: Новая
    - Источник: "parser"
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "Название сделки",
        "Контакт",
        "Должность",
        "Телефон",
        "Email",
        "Компания",
        "ИНН",
        "Источник",
        "Комментарий",
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for contact in contacts:
            writer.writerow(
                {
                    "Название сделки": f"{contact.object_name} — подключение PASS24",
                    "Контакт": contact.contact_name or "",
                    "Должность": contact.contact_role or "",
                    "Телефон": contact.contact_phone or "",
                    "Email": contact.contact_email or "",
                    "Компания": contact.org_name or "",
                    "ИНН": contact.org_inn or "",
                    "Источник": "parser",
                    "Комментарий": _build_comment(contact),
                }
            )

    logger.info("Bitrix24 CSV: %d записей → %s", len(contacts), output_path)
    return output_path
