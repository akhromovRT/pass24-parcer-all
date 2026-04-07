"""Квалификация контактов: quality_score и pre-CHAMP скоринг.

Спецификация из pipeline.md (этап 6).
"""

from __future__ import annotations

import logging

from pass24_parser.config import QUALITY_EXPORT_THRESHOLD, QUALITY_WEIGHTS
from pass24_parser.models import ParsedContact

logger = logging.getLogger(__name__)


def calculate_quality_score(contact: ParsedContact) -> float:
    """Рассчитывает quality_score (0-1) — полноту данных.

    Веса полей из pipeline.md:
    - Email ЛПР:           0.25
    - Телефон ЛПР:         0.20
    - ФИО ЛПР:             0.15
    - Размер объекта:       0.10
    - ИНН/ОГРН:            0.10
    - Наличие СКУД:         0.10
    - Наличие охраны:       0.10
    """
    score = 0.0

    if contact.contact_email:
        score += QUALITY_WEIGHTS["contact_email"]
    if contact.contact_phone:
        score += QUALITY_WEIGHTS["contact_phone"]
    if contact.contact_name:
        score += QUALITY_WEIGHTS["contact_name"]
    if contact.object_size is not None:
        score += QUALITY_WEIGHTS["object_size"]
    if contact.org_inn:
        score += QUALITY_WEIGHTS["org_inn"]
    if contact.has_skud is not None:
        score += QUALITY_WEIGHTS["has_skud"]
    if contact.has_security is not None:
        score += QUALITY_WEIGHTS["has_security"]

    return round(score, 2)


def calculate_pre_champ_score(contact: ParsedContact) -> int:
    """Рассчитывает pre-CHAMP score — предварительная оценка перспективности.

    Баллы из pipeline.md:
    - КП с охраной и >50 домов:  +30
    - Есть существующая СКУД:     +15
    - Нет СКУД, но есть охрана:   +20
    - ТСН/СНТ (не УК):            +10
    - МО и крупные города:         +10
    - <30 домов:                   -10
    - Нет контактных данных:       -20
    """
    score = 0

    # КП с охраной и >50 домов
    if (
        contact.object_type.value == "kp"
        and contact.has_security is True
        and (contact.object_size or 0) > 50
    ):
        score += 30

    # Есть существующая СКУД
    if contact.has_skud is True:
        score += 15

    # Нет СКУД, но есть охрана
    if contact.has_skud is False and contact.has_security is True:
        score += 20

    # ТСН/СНТ (не УК) — быстрое решение, один ЛПР
    org_lower = (contact.org_name or "").lower()
    if any(kw in org_lower for kw in ("тсн", "снт", "тсж")):
        score += 10

    # МО и крупные города
    region_lower = (contact.object_region or "").lower()
    if any(kw in region_lower for kw in ("москов", "петербург", "краснодар")):
        score += 10

    # <30 домов — низкая экономика
    if contact.object_size is not None and contact.object_size < 30:
        score -= 10

    # Нет контактных данных
    if not contact.contact_phone and not contact.contact_email:
        score -= 20

    return max(score, 0)


def qualify_contacts(contacts: list[ParsedContact]) -> list[ParsedContact]:
    """Квалифицирует список контактов: рассчитывает scores, фильтрует по порогу.

    Возвращает только записи с quality_score >= QUALITY_EXPORT_THRESHOLD (0.4).
    """
    qualified = []
    filtered_out = 0

    for contact in contacts:
        contact.quality_score = calculate_quality_score(contact)

        if contact.quality_score >= QUALITY_EXPORT_THRESHOLD:
            qualified.append(contact)
        else:
            filtered_out += 1

    logger.info(
        "Квалификация: %d прошли (порог %.1f), %d отфильтрованы",
        len(qualified), QUALITY_EXPORT_THRESHOLD, filtered_out,
    )
    return qualified
