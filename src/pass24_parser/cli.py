"""CLI точка входа — запуск парсера.

Использование:
  python -m pass24_parser                      # полный запуск (seed + DDG)
  python -m pass24_parser --region moscow_oblast
  python -m pass24_parser --seed-only          # только seed-список (быстро)
  python -m pass24_parser --ddg-only           # только DDG-поиск
  python -m pass24_parser --dadata-only        # только ЕГРЮЛ/dadata (ТСН/СНТ МО)
  python -m pass24_parser --all-sources        # все источники: seed + DDG + dadata
  python -m pass24_parser --export-only        # экспорт из БД без парсинга
  python -m pass24_parser --stats              # показать статистику БД

Автоэкспорт в Bitrix24: работает автоматически, если задан BITRIX24_WEBHOOK_URL в .env.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
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
        "--dadata-only",
        action="store_true",
        help="Только ЕГРЮЛ/dadata (ТСН/СНТ/ДНП МО через dadata.ru)",
    )
    p.add_argument(
        "--all-sources",
        action="store_true",
        help="Все источники: seed + DDG + dadata",
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


async def run_pipeline(
    region: str,
    seed_only: bool = False,
    ddg_only: bool = False,
    dadata_only: bool = False,
    all_sources: bool = False,
):
    """Запускает полный пайплайн: сбор → нормализация → обогащение → дедупликация → квалификация → экспорт.

    При наличии BITRIX24_WEBHOOK_URL автоматически экспортирует в Bitrix24 REST API.
    """
    from pass24_parser.collectors.ddg_search import DdgSearchCollector
    from pass24_parser.collectors.egrul_dadata import EgrulDadataCollector
    from pass24_parser.collectors.seed_urls import SeedUrlCollector
    from pass24_parser.deduplicator import deduplicate
    from pass24_parser.enricher import enrich_contact, enrich_from_web
    from pass24_parser.exporters.bitrix24 import export_to_csv
    from pass24_parser.http_client import close_client
    from pass24_parser.normalizer import normalize_contact
    from pass24_parser.qualifier import qualify_contacts
    from pass24_parser.storage import Storage

    logger = logging.getLogger(__name__)
    storage = Storage()
    today = date.today().strftime("%Y-%m-%d")

    # Определяем режим и порог квалификации
    if dadata_only:
        mode = "dadata"
        qual_threshold = 0.25  # ЕГРЮЛ-данные: ФИО+ИНН достаточно
    elif all_sources:
        mode = "seed + DDG + dadata"
        qual_threshold = 0.25  # dadata-контакты в батче
    else:
        mode = "seed" if seed_only else ("DDG" if ddg_only else "seed + DDG")
        qual_threshold = 0.4   # только веб-скрапинг — требуем телефон/email

    sep = "=" * 60
    print(sep)
    print("  PASS24 Parser")
    print(f"  Регион: {region}")
    print(f"  Режим: {mode}")
    print(f"  Порог квалификации: {qual_threshold}")
    print(f"  Дата: {today}")
    print(sep)

    try:
        all_contacts = []

        # 1a. Сбор из seed-списка
        if not ddg_only and not dadata_only:
            print("\n[1] Сбор данных из seed-списка URL...")
            seed_collector = SeedUrlCollector()
            seed_result = await seed_collector.collect(region)
            all_contacts.extend(seed_result.contacts)
            print(f"  [Seed] Собрано: {len(seed_result.contacts)} записей")

        # 1b. Сбор через DDG
        if not seed_only and not dadata_only:
            print("\n[1] Сбор данных через DuckDuckGo...")
            ddg_collector = DdgSearchCollector(max_results=50, scrape=True)
            ddg_result = await ddg_collector.collect(region)
            all_contacts.extend(ddg_result.contacts)
            print(f"  [DDG] Собрано: {len(ddg_result.contacts)} записей")

        # 1c. Сбор из ЕГРЮЛ/dadata
        if dadata_only or all_sources:
            print("\n[1] Сбор данных из ЕГРЮЛ через dadata.ru...")
            dadata_collector = EgrulDadataCollector()
            dadata_result = await dadata_collector.collect(region)
            all_contacts.extend(dadata_result.contacts)
            print(f"  [dadata] Собрано: {len(dadata_result.contacts)} записей")
            if dadata_result.errors:
                for err in dadata_result.errors[:3]:
                    print(f"  [dadata] Ошибка: {err}")

        total_raw = len(all_contacts)
        print(f"\n  Итого сырых: {total_raw}")

        # 2. Нормализация
        print("\n[2] Нормализация...")
        all_contacts = [normalize_contact(c) for c in all_contacts]

        # 3. Обогащение (ЕГРЮЛ nalog.ru) — пропускаем для dadata-only (уже обогащены)
        if not dadata_only:
            print("\n[3] Обогащение через ЕГРЮЛ...")
            enriched = []
            for c in all_contacts:
                enriched.append(await enrich_contact(c))
            all_contacts = enriched
        else:
            print("\n[3] Обогащение — пропуск (dadata уже содержит ЕГРЮЛ-данные)")

        # 3b. Веб-обогащение: ищем телефон/email для контактов без контактных данных
        no_contact = [c for c in all_contacts if not c.contact_phone and not c.contact_email]
        if no_contact:
            print(f"\n[3b] Веб-обогащение: {len(no_contact)} контактов без телефона/email...")
            web_found = 0
            for c in no_contact:
                try:
                    await enrich_from_web(c)
                    if c.contact_phone or c.contact_email:
                        web_found += 1
                        print(f"  [+] {c.object_name[:50]}: тел={c.contact_phone or '—'}  email={c.contact_email or '—'}")
                except Exception as exc:
                    logger.warning("Web-обогащение '%s': %s", c.object_name, exc)
            print(f"  Итого: нашли контакты {web_found}/{len(no_contact)}")

        # 4. Дедупликация
        print("\n[4] Дедупликация...")
        all_contacts = deduplicate(all_contacts)

        # 5. Квалификация
        print(f"\n[5] Квалификация (порог {qual_threshold})...")
        qualified = qualify_contacts(all_contacts, threshold=qual_threshold)

        # Сохранить в БД
        storage.save_contacts(qualified)

        # Экспорт в CSV
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        csv_path = OUTPUT_DIR / f"bitrix24_{region}_{today}.csv"
        export_to_csv(qualified, csv_path)

        # Автоэкспорт в Bitrix24 REST API (если задан BITRIX24_WEBHOOK_URL)
        api_stats = None
        if os.getenv("BITRIX24_WEBHOOK_URL") and qualified:
            print("\n[6] Экспорт в Bitrix24 REST API...")
            from pass24_parser.exporters.bitrix24_api import export_to_api
            contacts_with_sources = [(c, c.sources) for c in qualified]
            api_stats = export_to_api(contacts_with_sources)

        # Статистика
        db_stats = storage.get_stats()
        print(f"\n{sep}")
        print("  РЕЗУЛЬТАТЫ")
        print(sep)
        print(f"  Собрано сырых:       {total_raw}")
        print(f"  После дедупликации:  {len(all_contacts)}")
        print(f"  Квалифицировано:     {len(qualified)}")
        print(f"  Всего в БД:          {db_stats['total_contacts']}")
        print(f"  CSV: {csv_path}")
        if api_stats:
            print(f"  Bitrix24 создано:    {api_stats.created}")
            print(f"  Bitrix24 дублей:     {api_stats.skipped_dup}")
            print(f"  Bitrix24 клиентов:   {api_stats.skipped_existing_client}")
            print(f"  Bitrix24 ошибок:     {api_stats.errors}")
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
            dadata_only=args.dadata_only,
            all_sources=args.all_sources,
        ))


if __name__ == "__main__":
    main()
