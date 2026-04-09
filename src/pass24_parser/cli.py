"""CLI точка входа — запуск парсера.

Использование:
  python -m pass24_parser                      # полный запуск (seed + DDG)
  python -m pass24_parser --region moscow_oblast
  python -m pass24_parser --seed-only          # только seed-список (быстро)
  python -m pass24_parser --ddg-only           # только DDG-поиск
  python -m pass24_parser --export-only        # экспорт из БД без парсинга
  python -m pass24_parser --stats              # показать статистику БД
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

from pass24_parser.config import DATA_DIR, OUTPUT_DIR


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="PASS24 Parser — сбор контактов ЛПР"
    )
    p.add_argument(
        "--region",
        default="moscow_oblast",
        help="Целевой регион (default: moscow_oblast)",
    )
    p.add_argument(
        "--seed-only",
        action="store_true",
        help="Только seed-список URL (без DDG-поиска)",
    )
    p.add_argument(
        "--ddg-only",
        action="store_true",
        help="Только DDG-поиск (без seed-списка)",
    )
    p.add_argument(
        "--export-only",
        action="store_true",
        help="Только экспорт из БД, без парсинга",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Показать статистику БД",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Подробный вывод (DEBUG)",
    )
    return p.parse_args()


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def run_pipeline(region: str, seed_only: bool = False, ddg_only: bool = False):
    """Запускает полный пайплайн: сбор → нормализация → обогащение → дедупликация → квалификация → экспорт."""
    from pass24_parser.collectors.ddg_search import DdgSearchCollector
    from pass24_parser.collectors.seed_urls import SeedUrlCollector
    from pass24_parser.deduplicator import deduplicate
    from pass24_parser.enricher import enrich_contact
    from pass24_parser.exporters.bitrix24 import export_to_csv
    from pass24_parser.http_client import close_client
    from pass24_parser.normalizer import normalize_contact
    from pass24_parser.qualifier import qualify_contacts
    from pass24_parser.storage import Storage

    logger = logging.getLogger(__name__)
    storage = Storage()
    today = date.today().strftime("%Y-%m-%d")

    mode = "seed" if seed_only else ("DDG" if ddg_only else "seed + DDG")
    sep = "=" * 60
    print(sep)
    print("  PASS24 Parser — MVP")
    print(f"  Регион: {region}")
    print(f"  Режим: {mode}")
    print(f"  Дата: {today}")
    print(sep)

    try:
        all_contacts = []

        # 1a. Сбор из seed-списка
        if not ddg_only:
            print("\n[1/5] Сбор данных из seed-списка URL...")
            seed_collector = SeedUrlCollector()
            seed_result = await seed_collector.collect(region)
            all_contacts.extend(seed_result.contacts)
            print(f"  [Seed] Собрано: {len(seed_result.contacts)} записей")

        # 1b. Сбор через DDG
        if not seed_only:
            print("\n[1/5] Сбор данных через DuckDuckGo...")
            ddg_collector = DdgSearchCollector(max_results=50, scrape=True)
            ddg_result = await ddg_collector.collect(region)
            all_contacts.extend(ddg_result.contacts)
            print(f"  [DDG] Собрано: {len(ddg_result.contacts)} записей")

        total_raw = len(all_contacts)
        print(f"\n  Итого сырых: {total_raw}")

        # 2. Нормализация
        print("\n[2/5] Нормализация...")
        all_contacts = [normalize_contact(c) for c in all_contacts]

        # 3. Обогащение (ЕГРЮЛ)
        print("\n[3/5] Обогащение через ЕГРЮЛ...")
        enriched = []
        for c in all_contacts:
            enriched.append(await enrich_contact(c))
        all_contacts = enriched

        # 4. Дедупликация
        print("\n[4/5] Дедупликация...")
        all_contacts = deduplicate(all_contacts)

        # 5. Квалификация и экспорт
        print("\n[5/5] Квалификация и экспорт...")
        qualified = qualify_contacts(all_contacts)

        # Сохранить в БД
        storage.save_contacts(qualified)

        # Экспорт в CSV
        csv_path = OUTPUT_DIR / f"bitrix24_{region}_{today}.csv"
        export_to_csv(qualified, csv_path)

        # Статистика
        stats = storage.get_stats()
        print(f"\n{sep}")
        print("  РЕЗУЛЬТАТЫ")
        print(sep)
        print(f"  Собрано сырых:       {total_raw}")
        print(f"  После дедупликации:  {len(all_contacts)}")
        print(f"  Квалифицировано:     {len(qualified)}")
        print(f"  Всего в БД:          {stats['total_contacts']}")
        print(f"  CSV: {csv_path}")
        print(sep)

    finally:
        storage.close()
        await close_client()


async def show_stats():
    """Показывает статистику хранилища."""
    from pass24_parser.storage import Storage

    storage = Storage()
    stats = storage.get_stats()
    storage.close()

    print("Статистика БД:")
    print(f"  Всего контактов:     {stats['total_contacts']}")
    print(f"  С email:             {stats['with_email']}")
    print(f"  С телефоном:         {stats['with_phone']}")
    print(f"  Обработанных URL:    {stats['processed_urls']}")


async def export_only(region: str):
    """Экспорт существующих данных из БД без парсинга."""
    from pass24_parser.exporters.bitrix24 import export_to_csv
    from pass24_parser.qualifier import qualify_contacts
    from pass24_parser.storage import Storage

    storage = Storage()
    contacts = storage.load_contacts()
    storage.close()

    qualified = qualify_contacts(contacts)
    today = date.today().strftime("%Y-%m-%d")
    csv_path = OUTPUT_DIR / f"bitrix24_{region}_{today}.csv"
    export_to_csv(qualified, csv_path)
    print(f"Экспортировано {len(qualified)} контактов → {csv_path}")


def main():
    args = parse_args()
    setup_logging(args.verbose)

    if args.stats:
        asyncio.run(show_stats())
    elif args.export_only:
        asyncio.run(export_only(args.region))
    else:
        asyncio.run(run_pipeline(
            args.region,
            seed_only=args.seed_only,
            ddg_only=args.ddg_only,
        ))


if __name__ == "__main__":
    main()
