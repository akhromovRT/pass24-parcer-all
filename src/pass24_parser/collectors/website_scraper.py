"""Скрапер сайтов КП/ЖК — извлечение контактов с сайтов объектов.

Адаптировано из parser_v3.py: extract_contacts(), get_company_name(),
find_contact_page(), scrape_company().
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from pass24_parser.config import (
    CONTACT_PAGE_SLUGS,
    EMAIL_RE,
    PHONE_RE,
    SKIP_DOMAINS,
    TG_RE,
    VK_RE,
    WA_RE,
)
from pass24_parser.http_client import fetch
from pass24_parser.models import ParsedContact

logger = logging.getLogger(__name__)


def get_domain(url: str) -> str:
    """Извлекает домен без www."""
    try:
        return urlparse(url).netloc.lstrip("www.")
    except Exception:
        return ""


def is_skip_domain(url: str) -> bool:
    """Проверяет, что домен в чёрном списке агрегаторов."""
    domain = get_domain(url)
    return any(d in domain for d in SKIP_DOMAINS)


def extract_contacts_from_html(soup: BeautifulSoup, base_url: str) -> dict:
    """Извлекает контактную информацию из разобранного HTML.

    Из parser_v3.py extract_contacts() — проверенная логика:
    1. Ищет tel: и mailto: ссылки (структурированные данные)
    2. Fallback на regex по тексту страницы
    3. Извлекает VK, Telegram, WhatsApp
    4. Ищет адрес через schema.org itemprop
    """
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    full_text = soup.get_text(separator=" ")
    all_links = [a.get("href", "") for a in soup.find_all("a", href=True)]

    # Телефон
    phone = ""
    tel_links = [h for h in all_links if str(h).startswith("tel:")]
    if tel_links:
        phone = tel_links[0].replace("tel:", "").strip()
    if not phone:
        m = PHONE_RE.search(full_text)
        if m:
            phone = m.group(0)

    # Email
    email = ""
    mail_links = [h for h in all_links if str(h).startswith("mailto:")]
    if mail_links:
        email = mail_links[0].replace("mailto:", "").split("?")[0].strip()
    if not email:
        m = EMAIL_RE.search(full_text)
        if m:
            email = m.group(0)

    # VK
    vk_url = ""
    for link in all_links:
        m = VK_RE.search(str(link))
        if m and m.group(1) not in ("share", "sharer"):
            vk_url = link
            break

    # Telegram
    telegram = ""
    for link in all_links:
        m = TG_RE.search(str(link))
        if m:
            telegram = link
            break
    if not telegram:
        m = TG_RE.search(full_text)
        if m:
            telegram = m.group(0)

    # WhatsApp
    whatsapp = ""
    for link in all_links:
        if "wa.me" in str(link) or "whatsapp" in str(link).lower():
            whatsapp = link
            break
    if not whatsapp:
        m = WA_RE.search(full_text)
        if m:
            whatsapp = m.group(0)

    # Адрес (schema.org)
    address = ""
    for tag in soup.find_all(attrs={"itemprop": "address"}):
        t = tag.get_text(strip=True)
        if t:
            address = t[:200]
            break

    # Описание
    description = ""
    og_desc = soup.find("meta", property="og:description") or soup.find(
        "meta", attrs={"name": "description"}
    )
    if og_desc:
        description = og_desc.get("content", "").strip()[:300]

    return {
        "phone": phone,
        "email": email,
        "vk_url": vk_url,
        "telegram": telegram,
        "whatsapp": whatsapp,
        "address": address,
        "description": description,
    }


def get_org_name(soup: BeautifulSoup) -> str:
    """Определяет название организации из meta/schema.

    Из parser_v3.py get_company_name():
    1. schema.org itemprop="name"
    2. og:site_name
    3. <title> (первый сегмент)
    """
    for tag in soup.find_all(attrs={"itemprop": "name"}):
        t = tag.get_text(strip=True)
        if t and len(t) < 100:
            return t

    og = soup.find("meta", property="og:site_name")
    if og:
        val = og.get("content", "").strip()
        if val:
            return val[:100]

    if soup.title and soup.title.string:
        raw = soup.title.string.strip()
        for sep in [" | ", " — ", " - ", " :: "]:
            if sep in raw:
                return raw.split(sep)[0].strip()[:100]
        return raw[:100]

    return ""


def find_contact_page(base_url: str, soup: BeautifulSoup) -> Optional[str]:
    """Ищет ссылку на страницу контактов/руководства в навигации.

    Расширено относительно parser_v3: добавлены slug'и для КП
    (/pravlenie, /rukovodstvo, /management).
    """
    contact_kw = [
        "контакт", "contact", "о нас", "о компании", "связь",
        "руководств", "правлени", "management",
    ]
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").lower()
        text = a.get_text(strip=True).lower()
        if any(kw in href or kw in text for kw in contact_kw):
            full = urljoin(base_url, a["href"])
            if get_domain(full) == get_domain(base_url):
                return full
    return None


async def scrape_website(url: str, object_name: str = "") -> Optional[ParsedContact]:
    """Скрапит сайт организации/КП и возвращает ParsedContact.

    Адаптировано из parser_v3.py scrape_company():
    1. Загружает главную страницу
    2. Извлекает контакты
    3. Если нет телефона — ищет страницу контактов и скрапит её
    4. Мержит данные
    """
    if is_skip_domain(url):
        return None

    resp = await fetch(url)
    if resp is None:
        return None

    try:
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception:
        return None

    org_name = get_org_name(soup)
    contacts = extract_contacts_from_html(soup, url)

    # Если нет телефона — пробуем страницу контактов
    if not contacts["phone"]:
        contact_url = find_contact_page(url, soup)
        if contact_url:
            resp2 = await fetch(contact_url)
            if resp2:
                try:
                    soup2 = BeautifulSoup(resp2.text, "lxml")
                    contacts2 = extract_contacts_from_html(soup2, contact_url)
                    for field in ("phone", "email", "address", "telegram", "vk_url", "whatsapp"):
                        if not contacts[field] and contacts2[field]:
                            contacts[field] = contacts2[field]
                except Exception:
                    pass

    return ParsedContact(
        object_name=object_name or org_name or get_domain(url),
        object_address=contacts.get("address", ""),
        contact_phone=contacts.get("phone", ""),
        contact_email=contacts.get("email", ""),
        org_name=org_name,
        sources=[url],
    )
