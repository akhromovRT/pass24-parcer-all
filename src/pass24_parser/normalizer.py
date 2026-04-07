"""Нормализация данных: телефоны, email, адреса.

normalize_phone() адаптирован из parser_v3.py.
"""

from __future__ import annotations

import re

from pass24_parser.models import ParsedContact


def normalize_phone(phone: str) -> str:
    """Нормализует телефон в формат +7XXXXXXXXXX.

    Обрабатывает форматы: +7(...), 8(...), 10-значные номера.
    Из parser_v3.py normalize_phone().
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits[0] in ("7", "8"):
        return f"+7{digits[1:]}"
    if len(digits) == 10:
        return f"+7{digits}"
    return phone


def normalize_email(email: str) -> str:
    """Нормализует email: lowercase, trim пробелов."""
    if not email:
        return ""
    return email.strip().lower()


def normalize_address(address: str, region: str = "") -> str:
    """Приводит адрес к формату 'Регион, Город/Район, Название'."""
    if not address:
        return ""
    cleaned = " ".join(address.split())
    if region and region not in cleaned:
        return f"{region}, {cleaned}"
    return cleaned


def normalize_contact(contact: ParsedContact) -> ParsedContact:
    """Нормализует все поля контакта."""
    contact.contact_phone = normalize_phone(contact.contact_phone or "")
    contact.contact_email = normalize_email(contact.contact_email or "")
    contact.object_address = normalize_address(
        contact.object_address, contact.object_region
    )

    if contact.contact_name:
        contact.contact_name = " ".join(contact.contact_name.split())

    if contact.org_name:
        contact.org_name = " ".join(contact.org_name.split())

    return contact
