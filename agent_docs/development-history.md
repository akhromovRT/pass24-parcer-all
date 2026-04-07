# История разработки

Правило: хранить только последние 10 записей. При добавлении новой переносить старые в
`agent_docs/development-history-archive.md`. Архив читать при необходимости.

---

Краткий журнал итераций проекта.

## Записи

### [2026-04-07 — Инициализация проекта]

- **Что сделано:**
  - Заполнен блок описания проекта в `AGENTS.md` (цели, контекст, ограничения, смежные репозитории)
  - Заполнен `architecture.md` (6 компонентов: коллекторы, нормализатор, обогатитель, дедупликатор, квалификатор, экспортёры)
  - Создан `pipeline.md` — полный пайплайн от источников данных до экспорта в Bitrix24 и AI Sales Factory
  - Обновлены `index.md` и `development-history.md`
- **Зачем:** Зафиксировать контекст проекта на основе изучения `pass24-knowlege-base` (продукт, ICP, цикл продаж) и `pass24-ai-sales` (12 AI-агентов, формат Lead, CHAMP-скоринг, Bitrix24 интеграция). Без этого контекста невозможно спроектировать парсер, который будет давать данные нужного качества.
- **Обновлено:**
  - [x] `AGENTS.md` — описание проекта
  - [x] `agent_docs/architecture.md`
  - [x] `agent_docs/pipeline.md` (новый)
  - [x] `agent_docs/index.md`
  - [x] `agent_docs/development-history.md`
- **Следующие шаги:** ~~(выполнено в следующей итерации)~~

### [2026-04-07 — MVP: структура проекта и все модули]

- **Что сделано:**
  - Настроено окружение: .gitignore (Python), .cursorignore, .vscode/settings.json, .env.example
  - Создана модульная структура `src/pass24_parser/` (18 файлов)
  - Проанализирован `parser_v3.py` — извлечены утилиты (HTTP retry, regex, нормализация телефонов, извлечение контактов из HTML)
  - Модули: models (Pydantic), config, http_client (async httpx), normalizer, collectors (base + 2GIS + website_scraper), enricher (ЕГРЮЛ), deduplicator, qualifier (quality_score + pre-CHAMP), exporters (Bitrix24 CSV + AI Sales webhook), storage (SQLite), cli
  - pyproject.toml с зависимостями, venv создан и протестирован
- **Зачем:** Реализация полной структуры MVP-парсера по спецификации из architecture.md и pipeline.md. parser_v3.py использован как донор утилит (~150 строк), остальное написано с нуля.
- **Обновлено:**
  - [x] Все файлы в `src/pass24_parser/`
  - [x] pyproject.toml, .gitignore, .cursorignore, .env.example, .vscode/settings.json
  - [x] `agent_docs/development-history.md`
- **Следующие шаги:**
  - Тестировать 2GIS коллектор на реальных данных (2GIS рендерит через JS — нужен Playwright или API)
  - Тестировать ЕГРЮЛ обогатитель (captcha-ограничения)
  - Добавить тесты (pytest)
  - ADR: выбор метода парсинга 2GIS (API vs Playwright vs DuckDuckGo поиск)
