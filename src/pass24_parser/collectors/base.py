"""Базовый интерфейс коллектора."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pass24_parser.models import CollectorResult


class BaseCollector(ABC):
    """Базовый класс для всех коллекторов данных.

    Каждый коллектор собирает данные из конкретного источника
    и возвращает список ParsedContact через CollectorResult.
    """

    name: str = "base"

    @abstractmethod
    async def collect(self, region: str, **kwargs) -> CollectorResult:
        """Собрать данные из источника для указанного региона."""
        ...
