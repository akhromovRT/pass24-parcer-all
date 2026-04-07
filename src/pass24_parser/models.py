"""Модели данных проекта."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ObjectType(str, Enum):
    """Тип объекта недвижимости."""

    KP = "kp"
    ZHK = "zhk"
    BC = "bc"
    WAREHOUSE = "warehouse"
    INDUSTRIAL = "industrial"
    UNKNOWN = "unknown"


class ParsedContact(BaseModel):
    """Единая модель контакта ЛПР, собранного из источников.

    Соответствует спецификации из agent_docs/architecture.md.
    """

    # Идентификация объекта
    object_name: str
    object_type: ObjectType = ObjectType.UNKNOWN
    object_address: str = ""
    object_region: str = ""
    object_size: Optional[int] = None
    has_security: Optional[bool] = None
    has_skud: Optional[bool] = None

    # ЛПР
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

    # Организация (УК/ТСН)
    org_name: Optional[str] = None
    org_inn: Optional[str] = None
    org_ogrn: Optional[str] = None

    # Мета
    sources: list[str] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=datetime.now)
    quality_score: float = 0.0


class CollectorResult(BaseModel):
    """Результат работы коллектора — список сырых контактов."""

    source: str
    contacts: list[ParsedContact] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
