"""Тесты для website_scraper — извлечение метаданных объектов и ФИО ЛПР."""
from bs4 import BeautifulSoup

from pass24_parser.collectors.website_scraper import (
    _extract_object_size,
    _extract_person_name,
    _extract_security_info,
    _extract_skud_info,
)


class TestExtractObjectSize:
    def test_houses_count(self):
        soup = BeautifulSoup("<p>Посёлок на 120 домов с охраной</p>", "lxml")
        assert _extract_object_size(soup) == 120

    def test_plots_count(self):
        soup = BeautifulSoup("<p>Коттеджный поселок, 85 участков</p>", "lxml")
        assert _extract_object_size(soup) == 85

    def test_domovladeniy(self):
        soup = BeautifulSoup("<div>Состоит из 200 домовладений</div>", "lxml")
        assert _extract_object_size(soup) == 200

    def test_cottages(self):
        soup = BeautifulSoup("<p>В поселке 45 коттеджей</p>", "lxml")
        assert _extract_object_size(soup) == 45

    def test_no_size(self):
        soup = BeautifulSoup("<p>Красивый поселок у леса</p>", "lxml")
        assert _extract_object_size(soup) is None

    def test_ignores_small_numbers(self):
        soup = BeautifulSoup("<p>3 этажа, 5 комнат</p>", "lxml")
        assert _extract_object_size(soup) is None

    def test_ignores_too_large(self):
        soup = BeautifulSoup("<p>10000 домов в городе</p>", "lxml")
        assert _extract_object_size(soup) is None


class TestExtractSecurityInfo:
    def test_okhrana(self):
        soup = BeautifulSoup("<p>Круглосуточная охрана территории</p>", "lxml")
        assert _extract_security_info(soup) is True

    def test_kpp(self):
        soup = BeautifulSoup("<div>На въезде установлен КПП</div>", "lxml")
        assert _extract_security_info(soup) is True

    def test_videonablyudenie(self):
        soup = BeautifulSoup("<p>Видеонаблюдение по периметру</p>", "lxml")
        assert _extract_security_info(soup) is True

    def test_no_security(self):
        soup = BeautifulSoup("<p>Тихое место для отдыха</p>", "lxml")
        assert _extract_security_info(soup) is None


class TestExtractSkudInfo:
    def test_skud_direct(self):
        soup = BeautifulSoup("<p>Установлена система СКУД</p>", "lxml")
        assert _extract_skud_info(soup) is True

    def test_access_control(self):
        soup = BeautifulSoup("<p>Система контроля доступа на территорию</p>", "lxml")
        assert _extract_skud_info(soup) is True

    def test_propusk(self):
        soup = BeautifulSoup("<p>Пропускная система для жителей</p>", "lxml")
        assert _extract_skud_info(soup) is True

    def test_no_skud(self):
        soup = BeautifulSoup("<p>Охраняемая территория</p>", "lxml")
        assert _extract_skud_info(soup) is None


class TestExtractPersonName:
    def test_full_fio(self):
        soup = BeautifulSoup(
            "<div>Председатель правления — Иванов Иван Иванович</div>", "lxml"
        )
        name, role = _extract_person_name(soup)
        assert name == "Иванов Иван Иванович"
        assert "председатель" in role.lower()

    def test_short_fio(self):
        soup = BeautifulSoup("<p>Директор УК: Петров А.В.</p>", "lxml")
        name, role = _extract_person_name(soup)
        assert name == "Петров А.В."

    def test_rejects_navigation_text(self):
        soup = BeautifulSoup(
            "<p>Управляющая Безопасность Аэрофотосъемка Статьи</p>", "lxml"
        )
        name, _ = _extract_person_name(soup)
        assert name == ""

    def test_no_person(self):
        soup = BeautifulSoup("<p>Контакты: +7 999 123-45-67</p>", "lxml")
        name, _ = _extract_person_name(soup)
        assert name == ""
