"""Экспорт в AI Sales Factory — webhook JSON.

Формат из pipeline.md (этап 7b):
POST /webhooks/lead-form с metadata для CHAMP-скоринга.
"""

from __future__ import annotations

import logging
import os

from pass24_parser.http_client import get_client
from pass24_parser.models import ParsedContact
from pass24_parser.qualifier import calculate_pre_champ_score

logger = logging.getLogger(__name__)


def _contact_to_payload(contact: ParsedContact) -> dict:
    """Конвертирует ParsedContact в JSON-payload для webhook."""
    return {
        "source": "parser",
        "form_id": "pass24-parser-import",
        "contact_name": contact.contact_name or "",
        "phone": contact.contact_phone or "",
        "email": contact.contact_email or "",
        "company_name": contact.org_name or "",
        "metadata": {
            "object_name": contact.object_name,
            "object_type": contact.object_type.value,
            "object_address": contact.object_address,
            "object_size": contact.object_size,
            "has_security": contact.has_security,
            "has_skud": contact.has_skud,
            "management_type": _detect_management_type(contact),
            "org_inn": contact.org_inn or "",
            "org_ogrn": contact.org_ogrn or "",
            "contact_role": contact.contact_role or "",
            "quality_score": contact.quality_score,
            "pre_champ_score": calculate_pre_champ_score(contact),
        },
    }


def _detect_management_type(contact: ParsedContact) -> str:
    """Определяет тип управления (tsn/snt/uk) по названию организации."""
    org = (contact.org_name or "").lower()
    if "тсн" in org:
        return "tsn"
    if "снт" in org:
        return "snt"
    if "тсж" in org:
        return "tszh"
    return "uk"


async def export_to_webhook(contacts: list[ParsedContact]) -> dict:
    """Отправляет контакты в AI Sales Factory через webhook.

    Возвращает статистику: {sent: N, failed: N, errors: [...]}.
    """
    webhook_url = os.getenv("AI_SALES_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("AI_SALES_WEBHOOK_URL не задан, пропускаем webhook-экспорт")
        return {"sent": 0, "failed": 0, "errors": ["AI_SALES_WEBHOOK_URL не задан"]}

    client = await get_client()
    stats = {"sent": 0, "failed": 0, "errors": []}

    for contact in contacts:
        payload = _contact_to_payload(contact)
        try:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code in (200, 201):
                stats["sent"] += 1
            else:
                stats["failed"] += 1
                stats["errors"].append(
                    f"{contact.object_name}: HTTP {resp.status_code}"
                )
        except Exception as e:
            stats["failed"] += 1
            stats["errors"].append(f"{contact.object_name}: {e}")

    logger.info(
        "AI Sales webhook: %d отправлено, %d ошибок",
        stats["sent"], stats["failed"],
    )
    return stats
