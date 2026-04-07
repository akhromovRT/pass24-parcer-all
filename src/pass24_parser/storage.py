"""SQLite хранилище для персистентности между запусками.

Заменяет JSON-checkpoint из parser_v3.
Хранит собранные контакты, обработанные URL, историю запусков.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from pass24_parser.config import DB_PATH
from pass24_parser.models import ObjectType, ParsedContact

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_name TEXT NOT NULL,
    object_type TEXT DEFAULT 'unknown',
    object_address TEXT DEFAULT '',
    object_region TEXT DEFAULT '',
    object_size INTEGER,
    has_security INTEGER,
    has_skud INTEGER,
    contact_name TEXT,
    contact_role TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    org_name TEXT,
    org_inn TEXT,
    org_ogrn TEXT,
    sources TEXT DEFAULT '[]',
    collected_at TEXT NOT NULL,
    quality_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS processed_urls (
    url TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    processed_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contacts_inn ON contacts(org_inn);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(contact_email);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON contacts(contact_phone);
"""


class Storage:
    """SQLite-хранилище контактов."""

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def save_contacts(self, contacts: list[ParsedContact]) -> int:
        """Сохраняет контакты в БД. Возвращает количество сохранённых."""
        saved = 0
        for c in contacts:
            self.conn.execute(
                """INSERT INTO contacts
                   (object_name, object_type, object_address, object_region,
                    object_size, has_security, has_skud,
                    contact_name, contact_role, contact_email, contact_phone,
                    org_name, org_inn, org_ogrn,
                    sources, collected_at, quality_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    c.object_name, c.object_type.value, c.object_address, c.object_region,
                    c.object_size,
                    1 if c.has_security else (0 if c.has_security is False else None),
                    1 if c.has_skud else (0 if c.has_skud is False else None),
                    c.contact_name, c.contact_role, c.contact_email, c.contact_phone,
                    c.org_name, c.org_inn, c.org_ogrn,
                    json.dumps(c.sources, ensure_ascii=False),
                    c.collected_at.isoformat(),
                    c.quality_score,
                ),
            )
            saved += 1
        self.conn.commit()
        logger.info("Сохранено %d контактов в БД", saved)
        return saved

    def load_contacts(self) -> list[ParsedContact]:
        """Загружает все контакты из БД."""
        rows = self.conn.execute("SELECT * FROM contacts").fetchall()
        contacts = []
        for row in rows:
            contacts.append(
                ParsedContact(
                    object_name=row["object_name"],
                    object_type=ObjectType(row["object_type"]),
                    object_address=row["object_address"],
                    object_region=row["object_region"],
                    object_size=row["object_size"],
                    has_security=bool(row["has_security"]) if row["has_security"] is not None else None,
                    has_skud=bool(row["has_skud"]) if row["has_skud"] is not None else None,
                    contact_name=row["contact_name"],
                    contact_role=row["contact_role"],
                    contact_email=row["contact_email"],
                    contact_phone=row["contact_phone"],
                    org_name=row["org_name"],
                    org_inn=row["org_inn"],
                    org_ogrn=row["org_ogrn"],
                    sources=json.loads(row["sources"]),
                    collected_at=datetime.fromisoformat(row["collected_at"]),
                    quality_score=row["quality_score"],
                )
            )
        return contacts

    def is_url_processed(self, url: str) -> bool:
        """Проверяет, был ли URL уже обработан."""
        row = self.conn.execute(
            "SELECT 1 FROM processed_urls WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def mark_url_processed(self, url: str, source: str):
        """Помечает URL как обработанный."""
        self.conn.execute(
            "INSERT OR IGNORE INTO processed_urls (url, source) VALUES (?, ?)",
            (url, source),
        )
        self.conn.commit()

    def get_stats(self) -> dict:
        """Возвращает статистику хранилища."""
        total = self.conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        with_email = self.conn.execute(
            "SELECT COUNT(*) FROM contacts WHERE contact_email IS NOT NULL AND contact_email != ''"
        ).fetchone()[0]
        with_phone = self.conn.execute(
            "SELECT COUNT(*) FROM contacts WHERE contact_phone IS NOT NULL AND contact_phone != ''"
        ).fetchone()[0]
        urls = self.conn.execute("SELECT COUNT(*) FROM processed_urls").fetchone()[0]
        return {
            "total_contacts": total,
            "with_email": with_email,
            "with_phone": with_phone,
            "processed_urls": urls,
        }

    def close(self):
        self.conn.close()
