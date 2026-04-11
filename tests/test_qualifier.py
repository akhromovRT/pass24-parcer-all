"""Тесты для qualifier — quality_score и pre_champ_score."""
from pass24_parser.models import ObjectType, ParsedContact
from pass24_parser.qualifier import (
    calculate_pre_champ_score,
    calculate_quality_score,
    qualify_contacts,
)


def _make_contact(**kwargs) -> ParsedContact:
    defaults = {"object_name": "Тест КП", "object_type": ObjectType.KP}
    defaults.update(kwargs)
    return ParsedContact(**defaults)


class TestQualityScore:
    def test_empty_contact(self):
        c = _make_contact()
        assert calculate_quality_score(c) == 0.0

    def test_email_only(self):
        c = _make_contact(contact_email="test@test.ru")
        assert calculate_quality_score(c) == 0.25

    def test_email_and_phone(self):
        c = _make_contact(contact_email="t@t.ru", contact_phone="+79991234567")
        assert calculate_quality_score(c) == 0.45

    def test_with_name(self):
        c = _make_contact(
            contact_email="t@t.ru", contact_phone="+79991234567",
            contact_name="Иванов И.И."
        )
        assert calculate_quality_score(c) == 0.60

    def test_full_contact(self):
        c = _make_contact(
            contact_email="t@t.ru",
            contact_phone="+79991234567",
            contact_name="Иванов И.И.",
            object_size=100,
            org_inn="1234567890",
            has_skud=True,
            has_security=True,
        )
        assert calculate_quality_score(c) == 1.0

    def test_security_without_skud(self):
        c = _make_contact(has_security=True, has_skud=None)
        # has_security is not None → 0.10, has_skud is None → 0
        assert calculate_quality_score(c) == 0.10


class TestPreChampScore:
    def test_ideal_kp(self):
        c = _make_contact(
            has_security=True,
            object_size=80,
            has_skud=False,
            object_region="Московская область",
            org_name="ТСН Тестовое",
            contact_phone="+79991234567",
        )
        # +30 (КП с охраной >50) + 20 (нет СКУД но есть охрана) + 10 (ТСН) + 10 (МО)
        assert calculate_pre_champ_score(c) == 70

    def test_no_contacts(self):
        c = _make_contact()
        # -20 (нет контактов), max(0, -20) = 0
        assert calculate_pre_champ_score(c) == 0

    def test_small_kp(self):
        c = _make_contact(object_size=20, contact_phone="+79991234567")
        # -10 (<30 домов), max(0, -10) = 0
        assert calculate_pre_champ_score(c) == 0

    def test_with_skud(self):
        c = _make_contact(has_skud=True, contact_phone="+79991234567")
        assert calculate_pre_champ_score(c) == 15

    def test_mo_region(self):
        c = _make_contact(
            object_region="Московская область",
            contact_phone="+79991234567",
        )
        assert calculate_pre_champ_score(c) == 10


class TestQualifyContacts:
    def test_filters_low_quality(self):
        contacts = [
            _make_contact(contact_email="t@t.ru", contact_phone="+79991234567"),
            _make_contact(),
        ]
        result = qualify_contacts(contacts)
        assert len(result) == 1
        assert result[0].quality_score >= 0.4

    def test_empty_list(self):
        assert qualify_contacts([]) == []
