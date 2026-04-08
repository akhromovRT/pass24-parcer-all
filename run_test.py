"""Тестовый прогон парсера на 30 контактов."""

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pass24_parser.collectors.ddg_search import DdgSearchCollector
from pass24_parser.config import OUTPUT_DIR
from pass24_parser.deduplicator import deduplicate
from pass24_parser.exporters.bitrix24 import export_to_csv
from pass24_parser.http_client import close_client
from pass24_parser.normalizer import normalize_contact
from pass24_parser.qualifier import calculate_pre_champ_score, qualify_contacts
from pass24_parser.storage import Storage


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    today = date.today().strftime("%Y-%m-%d")
    sep = "=" * 60

    print(sep)
    print("  PASS24 Parser — Тестовый прогон (30 контактов)")
    print(f"  Дата: {today}")
    print(sep)

    try:
        # 1. Сбор через DDG
        collector = DdgSearchCollector(max_results=30, scrape=True)
        result = await collector.collect(region="moscow_oblast")

        print(f"\n  Сырых записей: {len(result.contacts)}")
        if result.errors:
            print(f"  Ошибок: {len(result.errors)}")

        # 2. Нормализация
        print("\n  Нормализация...")
        contacts = [normalize_contact(c) for c in result.contacts]

        # 3. Дедупликация
        print("  Дедупликация...")
        contacts = deduplicate(contacts)

        # 4. Квалификация
        print("  Квалификация...")
        qualified = qualify_contacts(contacts)

        # 5. Сохранение и экспорт
        storage = Storage()
        storage.save_contacts(contacts)  # сохраняем все, не только qualified

        csv_path = OUTPUT_DIR / f"test_bitrix24_{today}.csv"
        export_to_csv(qualified, csv_path)

        # Статистика
        print(f"\n{sep}")
        print("  РЕЗУЛЬТАТЫ")
        print(sep)
        print(f"  Собрано:            {len(result.contacts)}")
        print(f"  После дедупликации: {len(contacts)}")
        print(f"  Квалифицировано:    {len(qualified)} (quality ≥ 0.4)")

        # Детали
        with_phone = sum(1 for c in contacts if c.contact_phone)
        with_email = sum(1 for c in contacts if c.contact_email)
        kp_count = sum(1 for c in contacts if c.object_type.value == "kp")
        print(f"\n  С телефоном:        {with_phone}")
        print(f"  С email:            {with_email}")
        print(f"  Тип КП:             {kp_count}")

        # Топ-10 по quality
        contacts_sorted = sorted(contacts, key=lambda c: c.quality_score, reverse=True)
        print(f"\n  ТОП-10 по quality_score:")
        print(f"  {'Название':<35} {'Телефон':<16} {'Email':<25} {'Score':>5} {'CHAMP':>5}")
        print(f"  {'-'*35} {'-'*16} {'-'*25} {'-'*5} {'-'*5}")
        for c in contacts_sorted[:10]:
            champ = calculate_pre_champ_score(c)
            name = (c.object_name or "?")[:35]
            phone = (c.contact_phone or "—")[:16]
            email = (c.contact_email or "—")[:25]
            print(f"  {name:<35} {phone:<16} {email:<25} {c.quality_score:>5.2f} {champ:>5d}")

        print(f"\n  CSV: {csv_path}")
        stats = storage.get_stats()
        print(f"  БД:  {stats['total_contacts']} контактов")
        print(sep)

        storage.close()

    finally:
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())
