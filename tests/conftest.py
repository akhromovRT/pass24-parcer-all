"""Pytest конфигурация и общие фикстуры."""
import sys
from pathlib import Path

# Добавляем src в path для импорта (iCloud пробелы в пути)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
