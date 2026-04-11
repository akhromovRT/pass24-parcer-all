"""Тесты для DDG фильтра релевантности."""
from pass24_parser.collectors.ddg_search import _is_relevant


class TestIsRelevant:
    # Реальные КП — должны проходить
    def test_kp_site_passes(self):
        assert _is_relevant(
            "https://kp-nikolskoe.ru/",
            "КП Никольское",
            "Коттеджный поселок Никольское Московская область",
        )

    def test_kp_domain_passes(self):
        assert _is_relevant(
            "https://kp-mastergrad.ru/",
            "Мастерград",
            "Официальный сайт",
        )

    def test_primary_keyword_passes(self):
        assert _is_relevant(
            "https://example.ru/",
            "Поселок Солнечный",
            "Коттеджный поселок Солнечный — контакты и управление",
        )

    # Ложные срабатывания — должны блокироваться
    def test_blocks_ukrainian_tv(self):
        assert not _is_relevant(
            "https://24tv.ua/", "24 Канал", "Новости Украины"
        )

    def test_blocks_news(self):
        assert not _is_relevant(
            "https://tsn24.ru/", "Новости Тулы", "ТСН тульские новости"
        )

    def test_blocks_informational(self):
        assert not _is_relevant(
            "https://sntclub.ru/create-tsn",
            "Как создать ТСН",
            "Регистрация ТСН пошаговая инструкция",
        )

    def test_blocks_service_company(self):
        assert not _is_relevant(
            "https://example.ru/remont",
            "Ремонт квартир",
            "Услуги ремонт квартир и дизайн интерьер",
        )

    def test_blocks_catalog_articles(self):
        assert not _is_relevant(
            "https://catalog.ru/top",
            "Топ коттеджных поселков",
            "Рейтинг коттеджных поселков Подмосковья 2026",
        )

    # Граница: 1 secondary недостаточно, 2+ проходит
    def test_single_secondary_blocks(self):
        assert not _is_relevant(
            "https://example.ru/", "Компания", "поселок у реки"
        )

    def test_two_secondary_passes(self):
        assert _is_relevant(
            "https://example.ru/",
            "Управление поселком",
            "ТСН председатель правления поселка",
        )
