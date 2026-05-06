"""Удаляет лиды парсера без телефона и email из Bitrix24.

Запуск (из корня проекта, с активным venv):
    python scripts/delete_no_contact_leads.py          # интерактивно
    python scripts/delete_no_contact_leads.py --yes    # без подтверждения (CI)

Что делает:
- Ищет лиды с SOURCE_ID=PARSER и STATUS_ID=UC_PARSER
- Из них выбирает те, у кого НЕТ ни телефона, ни email
- Удаляет их через crm.lead.delete
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Загружаем .env вручную (без python-dotenv)
env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

WEBHOOK = os.getenv("BITRIX24_WEBHOOK_URL", "").rstrip("/")
if not WEBHOOK:
    raise SystemExit("BITRIX24_WEBHOOK_URL не задан в .env")

_ssl_ctx = ssl.create_default_context()


def b24(method: str, data: dict | None = None) -> dict:
    url = f"{WEBHOOK}/{method}"
    for attempt in range(3):
        try:
            if data:
                body = urllib.parse.urlencode(data, doseq=True).encode()
                req = urllib.request.Request(url, data=body, method="POST")
            else:
                req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=25, context=_ssl_ctx) as r:
                return json.loads(r.read())
        except Exception as exc:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise
    return {}


def get_parser_leads() -> list[dict]:
    """Загружает все лиды парсера (SOURCE_ID=PARSER)."""
    leads: list[dict] = []
    start = 0
    while True:
        r = b24("crm.lead.list", {
            "filter[SOURCE_ID]": "PARSER",
            "filter[STATUS_ID]": "UC_PARSER",
            "SELECT[]": ["ID", "TITLE", "PHONE", "EMAIL"],
            "start": start,
        })
        batch = r.get("result", [])
        if not batch:
            break
        leads.extend(batch)
        total = r.get("total", 0)
        start += 50
        if start >= total:
            break
        time.sleep(0.3)
    return leads


def main():
    auto_yes = "--yes" in sys.argv or os.getenv("CI") == "true"

    print("Загружаю лиды парсера из Bitrix24...")
    leads = get_parser_leads()
    print(f"Всего лидов SOURCE=PARSER, STATUS=UC_PARSER: {len(leads)}")

    no_contact = []
    for lead in leads:
        phones = lead.get("PHONE") or []
        emails = lead.get("EMAIL") or []
        has_phone = any(p.get("VALUE") for p in phones if isinstance(p, dict))
        has_email = any(e.get("VALUE") for e in emails if isinstance(e, dict))
        if not has_phone and not has_email:
            no_contact.append(lead)

    print(f"\nЛиды без телефона И без email: {len(no_contact)}")
    if not no_contact:
        print("Нечего удалять.")
        return

    print("\nСписок к удалению:")
    for lead in no_contact:
        print(f"  #{lead['ID']} — {lead['TITLE']}")

    if not auto_yes:
        confirm = input(f"\nУдалить {len(no_contact)} лидов? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Отменено.")
            return
    else:
        print(f"\nАвто-подтверждение (CI). Удаляю {len(no_contact)} лидов...")

    deleted = 0
    for lead in no_contact:
        try:
            r = b24("crm.lead.delete", {"id": lead["ID"]})
            if r.get("result"):
                print(f"  [OK] Удалён #{lead['ID']}")
                deleted += 1
            else:
                print(f"  [ERR] #{lead['ID']}: {r}")
            time.sleep(0.3)
        except Exception as exc:
            print(f"  [ERR] #{lead['ID']}: {exc}")

    print(f"\nГотово. Удалено: {deleted}/{len(no_contact)}")


if __name__ == "__main__":
    main()
