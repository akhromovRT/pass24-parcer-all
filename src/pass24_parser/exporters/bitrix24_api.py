"""Экспорт в Bitrix24 CRM через REST API.

Создаёт лиды в разделе «Лиды», стадия UC_PARSER, источник PARSER.
Перед созданием:
  1. Проверяет дубли по телефону/email (crm.duplicate.findByComm)
  2. Проверяет, не является ли объект существующим клиентом
     (ищет совпадение уникальных слов-якорей среди всех сделок Bitrix24)

Настройка через .env:
  BITRIX24_WEBHOOK_URL   — URL вебхука (обязателен)
  BITRIX24_RESPONSIBLE   — ID ответственного (по умолчанию 16, Павел Мельников)
"""

from __future__ import annotations

import logging
import os
import re
import time
import json
import urllib.request
import urllib.parse
import ssl
from dataclasses import dataclass, field

from pass24_parser.models import ParsedContact
from pass24_parser.qualifier import calculate_pre_champ_score

logger = logging.getLogger(__name__)

# ── Константы ──────────────────────────────────────────────────────────────
STATUS_ID = "UC_PARSER"
SOURCE_ID = "PARSER"
DEFAULT_RESPONSIBLE = 16  # Павел Мельников

# Нарицательные географические слова — не дают уникальной идентификации объекта
_GEO_COMMON = {
    "парк", "озеро", "берег", "бор", "лес", "поле", "гора", "сад", "дача",
    "деревня", "слобода", "усадьба", "долина", "луга", "пески", "зори",
    "поляна", "аллея", "пруды", "пруд", "мыс", "мир", "свет", "новый",
    "новая", "белый", "белое", "зеленый", "зелёный", "золотой", "солнечный",
    "светлый", "лагуна", "резиденция", "residence", "estate", "village",
    "хиллз", "hills", "парки", "сады", "рощи", "леса", "поля", "тишина",
    "сосновый", "берёзовый", "дубовый", "еловый", "облако", "монтаж",
    "оборудование", "подключение", "интеграция",
    # Родовые слова для КП — не дают уникальной идентификации
    "поселок", "посёлок", "поселка", "посёлка", "поселки", "посёлки",
    "коттедж", "коттеджный", "загородный", "земля", "участок",
}

# Слова из служебных частей названий сделок (не идентификаторы объекта)
_DEAL_NOISE = {
    "upsale", "лид", "алексей", "максим", "павел", "тест", "поставка",
    "аудит", "работы", "замена", "pass24", "скуд", "шлагбаум", "брелки",
    "кодонаборная", "панель", "контроллер", "лицензия", "сигур", "паркинг",
    "распознавание", "номеров", "объезды", "монтаж", "поставка",
}


# ── HTTP helper ─────────────────────────────────────────────────────────────
_ssl_ctx = ssl.create_default_context()


def _b24(method: str, data: dict | None = None, retries: int = 3) -> dict:
    webhook = os.getenv("BITRIX24_WEBHOOK_URL", "").rstrip("/")
    if not webhook:
        raise RuntimeError("BITRIX24_WEBHOOK_URL не задан в .env")
    url = f"{webhook}/{method}"
    for attempt in range(retries):
        try:
            if data:
                body = urllib.parse.urlencode(data, doseq=True).encode()
                req = urllib.request.Request(url, data=body, method="POST")
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=25, context=_ssl_ctx) as r:
                return json.loads(r.read())
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2**attempt)
            else:
                raise
    return {}


# ── Вспомогательные функции ─────────────────────────────────────────────────

def _anchor_words(text: str) -> set[str]:
    """Уникальные слова-якоря: длина ≥5, не нарицательные географические."""
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return {w for w in words if len(w) >= 5
            and w not in _GEO_COMMON and w not in _DEAL_NOISE}


def _parse_fio(fio: str) -> tuple[str, str, str]:
    """«Фамилия Имя Отчество» → (имя, фамилия, отчество)."""
    parts = (fio or "").strip().split()
    if len(parts) >= 3:
        return parts[1], parts[0], parts[2]
    if len(parts) == 2:
        return parts[1], parts[0], ""
    return fio or "", "", ""


@dataclass
class ExportStats:
    created: int = 0
    skipped_dup: int = 0
    skipped_existing_client: int = 0
    skipped_no_contact: int = 0
    errors: int = 0
    details: list[dict] = field(default_factory=list)


# ── Загрузка существующих клиентов ─────────────────────────────────────────

def fetch_all_deals() -> list[dict]:
    """Загружает все сделки из воронок ОБЛАКО (2) и ОБОРУДОВАНИЕ (4)."""
    all_deals: list[dict] = []
    for cat_id in ("2", "4"):
        last_id = 0
        while True:
            r = _b24("crm.deal.list", {
                "filter[CATEGORY_ID]": cat_id,
                "filter[>ID]": last_id,
                "SELECT[]": ["ID", "TITLE"],
                "order[ID]": "ASC",
                "start": -1,
            })
            batch = r.get("result", [])
            if not batch:
                break
            all_deals.extend(batch)
            last_id = batch[-1]["ID"]
            if len(batch) < 50:
                break
            time.sleep(0.3)
    logger.info("Загружено сделок из Bitrix24: %d", len(all_deals))
    return all_deals


def build_existing_client_index(deals: list[dict]) -> dict[str, list[dict]]:
    """Строит индекс {слово-якорь: [сделки]} для быстрой проверки."""
    index: dict[str, list[dict]] = {}
    for deal in deals:
        for word in _anchor_words(deal["TITLE"]):
            index.setdefault(word, []).append(deal)
    return index


def is_existing_client(
    contact: ParsedContact,
    index: dict[str, list[dict]],
) -> tuple[bool, str]:
    """Проверяет, совпадает ли объект с известной сделкой.

    Требует минимум 1 слово-якорь длиной ≥5 символов (или 2 слова ≥4 символов).
    Возвращает (True, причина) если совпадение найдено.
    """
    name_anchors = _anchor_words(contact.object_name or "")
    if not name_anchors:
        return False, ""

    hit_deals: set[str] = set()
    hit_words: list[str] = []
    for word in name_anchors:
        if word in index:
            for deal in index[word]:
                did = str(deal["ID"])
                if did not in hit_deals:
                    hit_deals.add(did)
                    hit_words.append(f'«{word}» → сделка #{deal["ID"]} "{deal["TITLE"][:50]}"')

    if hit_deals:
        reason = "Объект уже присутствует в Bitrix24: " + "; ".join(hit_words[:2])
        return True, reason
    return False, ""


# ── Дедупликация ────────────────────────────────────────────────────────────

def check_duplicate(phone: str, email: str, inn: str) -> tuple[bool, str]:
    """Проверяет дубли по телефону, email, ИНН компании."""
    if phone:
        digits = "".join(c for c in phone if c.isdigit())[-10:]
        r = _b24("crm.duplicate.findByComm", {"type": "PHONE", "values[]": digits})
        res = r.get("result")
        if isinstance(res, dict) and (res.get("LEAD") or res.get("CONTACT")):
            return True, f"дубль по телефону {phone}"
        time.sleep(0.3)

    if email:
        r = _b24("crm.duplicate.findByComm", {"type": "EMAIL", "values[]": email})
        res = r.get("result")
        if isinstance(res, dict) and (res.get("LEAD") or res.get("CONTACT")):
            return True, f"дубль по email {email}"
        time.sleep(0.3)

    if inn and len(inn) >= 10:
        r = _b24("crm.company.list", {
            "filter[%TITLE]": inn,
            "SELECT[]": ["ID", "TITLE"],
            "start": -1,
        })
        if r.get("result"):
            return True, f"дубль по ИНН {inn}"
        time.sleep(0.3)

    return False, ""


# ── Создание лида ───────────────────────────────────────────────────────────

def _source_label(sources_list: list[str]) -> str:
    """Человекочитаемое название источника данных."""
    for s in sources_list:
        if "egrul_dadata" in s:
            return "ЕГРЮЛ/dadata"
        if s.startswith("http"):
            return "Сайт КП"
    return "DDG"


def _build_comment(contact: ParsedContact, sources_list: list[str]) -> str:
    obj_type_map = {"kp": "Коттеджный посёлок / ТСН / СНТ", "zhk": "ЖК", "bc": "Бизнес-центр"}
    region = contact.object_region or "Московская область"
    src_label = _source_label(sources_list)

    lines = [
        f"Регион: {region}",
        f"Источник данных: {src_label}",
        "Данные получены парсером PASS24",
        "",
    ]
    lines.append(f"Тип объекта: {obj_type_map.get(contact.object_type.value, 'Объект')}")
    if contact.object_address:
        lines.append(f"Адрес: {contact.object_address.replace(chr(10), ' ').strip()[:300]}")
    if contact.object_size:
        lines.append(f"Домов/квартир: {contact.object_size}")
    lines.append(f"Охрана/КПП: {'Да' if contact.has_security else 'Нет'}")
    lines.append(f"Существующая СКУД: {'Да' if contact.has_skud else 'Нет'}")
    if contact.org_name:
        lines.append(f"Организация: {contact.org_name}")
    if contact.org_inn:
        lines.append(f"ИНН: {contact.org_inn}")
    if contact.org_ogrn:
        lines.append(f"ОГРН: {contact.org_ogrn}")
    if contact.contact_role:
        lines.append(f"Должность ЛПР: {contact.contact_role}")
    lines.append(f"Quality score: {contact.quality_score:.2f}")
    lines.append(f"Pre-CHAMP: {calculate_pre_champ_score(contact)}")
    primary = next(
        (s for s in sources_list if s.startswith("http") and "egrul" not in s), ""
    )
    if primary:
        lines.append(f"Источник (сайт): {primary}")
    elif any("egrul_dadata" in s for s in sources_list):
        inn = contact.org_inn or ""
        if inn:
            lines.append(f"Проверить в ЕГРЮЛ: https://egrul.nalog.ru/?query={inn}")
    return "\n".join(lines)


def create_lead(contact: ParsedContact, sources_list: list[str]) -> int | None:
    """Создаёт лид в Bitrix24. Возвращает ID или None при ошибке."""
    responsible = int(os.getenv("BITRIX24_RESPONSIBLE", str(DEFAULT_RESPONSIBLE)))
    first, last, middle = _parse_fio(contact.contact_name or "")

    data: dict = {
        "fields[TITLE]": f"{contact.object_name} — подключение PASS24",
        "fields[NAME]": first or contact.object_name,
        "fields[LAST_NAME]": last,
        "fields[SECOND_NAME]": middle,
        "fields[POST]": contact.contact_role or "",
        "fields[COMPANY_TITLE]": contact.org_name or "",
        "fields[SOURCE_ID]": SOURCE_ID,
        "fields[STATUS_ID]": STATUS_ID,
        "fields[ASSIGNED_BY_ID]": responsible,
        "fields[COMMENTS]": _build_comment(contact, sources_list),
    }
    if contact.contact_phone:
        data["fields[PHONE][0][VALUE]"] = contact.contact_phone
        data["fields[PHONE][0][VALUE_TYPE]"] = "WORK"
    if contact.contact_email:
        data["fields[EMAIL][0][VALUE]"] = contact.contact_email
        data["fields[EMAIL][0][VALUE_TYPE]"] = "WORK"

    r = _b24("crm.lead.add", data)
    lead_id = r.get("result")
    return int(lead_id) if lead_id and str(lead_id).isdigit() else None


# ── Основная функция экспорта ───────────────────────────────────────────────

def export_to_api(
    contacts: list[tuple[ParsedContact, list[str]]],
    *,
    skip_pause: float = 0.5,
) -> ExportStats:
    """Экспортирует контакты в Bitrix24 через REST API.

    Args:
        contacts: список пар (ParsedContact, sources_list).
        skip_pause: пауза между запросами (секунды).

    Перед созданием каждого лида:
      - Проверяет, что объект не является существующим клиентом Bitrix24
      - Проверяет дубли по телефону/email
    """
    stats = ExportStats()

    # Один раз загружаем все сделки для проверки существующих клиентов
    logger.info("Загружаю индекс существующих клиентов из Bitrix24...")
    all_deals = fetch_all_deals()
    client_index = build_existing_client_index(all_deals)
    logger.info("Индекс построен: %d уникальных слов-якорей", len(client_index))

    for contact, sources in contacts:
        name = contact.object_name or "Без названия"
        phone = contact.contact_phone or ""
        email = contact.contact_email or ""

        # Нет контактных данных.
        # Исключение: ЕГРЮЛ/dadata контакты с ФИО + ИНН достаточно верифицированы
        # для передачи в Bitrix — sales может найти телефон вручную по ИНН.
        is_egrul = any("egrul_dadata" in s for s in contact.sources)
        has_egrul_id = is_egrul and bool(contact.contact_name) and bool(contact.org_inn)
        if not phone and not email and not has_egrul_id:
            stats.skipped_no_contact += 1
            stats.details.append({"status": "ПРОПУЩЕН", "name": name, "reason": "нет телефона и email"})
            continue

        # Проверка: существующий клиент Bitrix24
        is_client, client_reason = is_existing_client(contact, client_index)
        if is_client:
            stats.skipped_existing_client += 1
            stats.details.append({"status": "КЛИЕНТ", "name": name, "reason": client_reason})
            logger.info("[КЛИЕНТ] %s — %s", name, client_reason)
            continue

        # Проверка: дубль по телефону/email
        is_dup, dup_reason = check_duplicate(phone, email, contact.org_inn or "")
        if is_dup:
            stats.skipped_dup += 1
            stats.details.append({"status": "ДУБЛЬ", "name": name, "reason": dup_reason})
            logger.info("[DUP] %s — %s", name, dup_reason)
            continue

        # Создаём лид
        try:
            lead_id = create_lead(contact, sources)
            if lead_id:
                stats.created += 1
                stats.details.append({"status": "СОЗДАН", "name": name, "lead_id": lead_id})
                logger.info("[OK] %s → Лид #%d", name, lead_id)
            else:
                stats.errors += 1
                stats.details.append({"status": "ОШИБКА", "name": name, "reason": "пустой ответ API"})
            time.sleep(skip_pause)
        except Exception as exc:
            stats.errors += 1
            stats.details.append({"status": "ОШИБКА", "name": name, "reason": str(exc)})
            logger.error("[ERR] %s — %s", name, exc)
            time.sleep(1)

    return stats
