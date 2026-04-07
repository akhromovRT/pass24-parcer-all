"""Async HTTP-клиент с retry и экспоненциальным бэкофом.

Логика retry адаптирована из parser_v3.py get_with_retry().
Переведено с requests на httpx (async).
"""

from __future__ import annotations

import asyncio
import logging
import random

from typing import Optional

import httpx

from pass24_parser.config import HEADERS, HTTP_TIMEOUT, MAX_RETRY

logger = logging.getLogger(__name__)

_client: Optional[httpx.AsyncClient] = None


async def get_client() -> httpx.AsyncClient:
    """Возвращает переиспользуемый async-клиент."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        )
    return _client


async def close_client() -> None:
    """Закрывает клиент (вызывать при завершении)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def fetch(
    url: str,
    *,
    max_retry: int = MAX_RETRY,
    timeout: int = HTTP_TIMEOUT,
) -> Optional[httpx.Response]:
    """GET-запрос с retry и экспоненциальным бэкофом.

    Возвращает Response или None если все попытки провалились.
    Не повторяет запрос при 403, 404, 410 (бессмысленно).
    """
    client = await get_client()

    for attempt in range(1, max_retry + 1):
        try:
            resp = await client.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp

        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            if code in (403, 404, 410):
                logger.debug("HTTP %d для %s — пропускаем", code, url)
                return None
            wait = 2**attempt + random.uniform(0, 1)
            logger.warning(
                "HTTP %d для %s, попытка %d/%d, ждём %.1fс",
                code, url, attempt, max_retry, wait,
            )
            await asyncio.sleep(wait)

        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            wait = 2**attempt + random.uniform(0, 1)
            logger.warning(
                "Timeout/Connection для %s, попытка %d/%d, ждём %.1fс",
                url, attempt, max_retry, wait,
            )
            await asyncio.sleep(wait)

        except httpx.HTTPError as e:
            logger.error("Fetch error для %s: %s", url, e)
            return None

    logger.error("Все %d попыток исчерпаны для %s", max_retry, url)
    return None
