"""Тесты для normalizer — нормализация телефонов, email, адресов."""
from pass24_parser.normalizer import normalize_address, normalize_email, normalize_phone


class TestNormalizePhone:
    def test_plus7_format(self):
        assert normalize_phone("+7 (495) 123-45-67") == "+74951234567"

    def test_eight_format(self):
        assert normalize_phone("8 (495) 123-45-67") == "+74951234567"

    def test_ten_digits(self):
        assert normalize_phone("9991234567") == "+79991234567"

    def test_already_normalized(self):
        assert normalize_phone("+79991234567") == "+79991234567"

    def test_empty(self):
        assert normalize_phone("") == ""

    def test_short_number(self):
        result = normalize_phone("12345")
        assert result == "12345"

    def test_with_dashes(self):
        assert normalize_phone("+7-999-123-45-67") == "+79991234567"


class TestNormalizeEmail:
    def test_lowercase(self):
        assert normalize_email("User@Example.COM") == "user@example.com"

    def test_trim_spaces(self):
        assert normalize_email("  user@test.ru  ") == "user@test.ru"

    def test_empty(self):
        assert normalize_email("") == ""


class TestNormalizeAddress:
    def test_adds_region(self):
        result = normalize_address("ул. Ленина, 1", "МО")
        assert result == "МО, ул. Ленина, 1"

    def test_no_duplicate_region(self):
        result = normalize_address("МО, ул. Ленина, 1", "МО")
        assert result.count("МО") == 1

    def test_empty(self):
        assert normalize_address("") == ""

    def test_collapses_whitespace(self):
        result = normalize_address("ул.  Ленина,   1")
        assert "  " not in result
