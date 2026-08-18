import aiohttp
import asyncio
import ssl
import certifi
from datetime import date
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Ожидание при rate limit (секунды)
RATE_LIMIT_WAIT = 65

class WBAPIClient:
    def __init__(self):
        self.fin_base_url = "https://finance-api.wildberries.ru/api/finance/v1"  #"https://statistics-api.wildberries.ru/api/v5/supplier"
        self.content_base_url = "https://content-api.wildberries.ru/content/v2"
        self.analytics_base_url = "https://seller-analytics-api.wildberries.ru/api"

    async def get_report_detail_by_period(
        self,
        api_key: str,
        date_from: date,
        date_to: date,
        limit: int = 100000,
        rrdid: int = 0,
        max_retries: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        ОДИН запрос к WB API /sales-reports/detailed
        При 429 — ждёт 65 секунд и повторяет (до max_retries раз).
        """
        headers = {"Authorization": api_key}
        body = {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "limit": limit,
            "rrdId": rrdid,
        }

        ssl_context = ssl.create_default_context(cafile=certifi.where())

        for attempt in range(1, max_retries + 1):
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            try:
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.post(
                        f"{self.fin_base_url}/sales-reports/detailed",
                        headers=headers,
                        json=body,
                        timeout=aiohttp.ClientTimeout(total=65),
                    ) as response:

                        if response.status == 200:
                            data = await response.json()
                            logger.info(f"📥 Received {len(data)} records (rrdid={rrdid})")
                            return data

                        elif response.status == 401:
                            raise Exception("Invalid API Key")

                        elif response.status == 429:
                            if attempt < max_retries:
                                logger.warning(
                                    f"⏳ Rate limit hit (attempt {attempt}/{max_retries}), "
                                    f"waiting {RATE_LIMIT_WAIT}s..."
                                )
                                await asyncio.sleep(RATE_LIMIT_WAIT)
                                continue
                            else:
                                raise Exception(
                                    f"Rate limit exceeded after {max_retries} retries"
                                )

                        else:
                            error_text = await response.text()
                            raise Exception(f"WB API error {response.status}: {error_text}")

            except Exception as e:
                # Пробрасываем дальше только если это не rate limit retry
                if "Rate limit" not in str(e) or attempt >= max_retries:
                    logger.error(f"WB API request failed (attempt {attempt}): {str(e)}")
                    raise

        raise Exception("Unexpected end of retry loop")

    async def get_product_data_by_sku(
        self,
        api_key: str,
        sku: str,
        limit: int = 100,
        with_photo: int = -1,
        max_retries: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Карточки товара из WB Content API (POST /get/cards/list).
        При 429 — ждёт 65 секунд и повторяет (до max_retries раз), по аналогии
        с финансовым API и stocks-report.

        Ретраи здесь критичны: фото запрашивается только при создании товара,
        и без ретраев один-единственный 429 означал, что фото этого товара
        не будет загружено никогда (повторного запроса для существующих нет).
        """

        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }

        payload = {
                        "settings": {
                            "cursor": {
                                "limit": limit
                            },
                            "filter": {
                                "textSearch": sku,
                                "withPhoto": with_photo
                            }
                        }
                    }

        ssl_context = ssl.create_default_context(cafile=certifi.where())

        for attempt in range(1, max_retries + 1):
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            try:
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.post(
                        f"{self.content_base_url}/get/cards/list",
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=61)
                    ) as response:

                        if response.status == 200:
                            data = await response.json()
                            return data.get("cards", [])

                        elif response.status == 401:
                            raise Exception("Invalid API Key")

                        elif response.status == 429:
                            if attempt < max_retries:
                                logger.warning(
                                    f"⏳ Rate limit hit on content-api (attempt {attempt}/{max_retries}), "
                                    f"waiting {RATE_LIMIT_WAIT}s..."
                                )
                                await asyncio.sleep(RATE_LIMIT_WAIT)
                                continue
                            else:
                                raise Exception(
                                    f"Rate limit exceeded after {max_retries} retries"
                                )

                        else:
                            error_text = await response.text()
                            raise Exception(f"WB API error {response.status}: {error_text}")

            except Exception as e:
                if "Rate limit" not in str(e) or attempt >= max_retries:
                    logger.error(f"WB content-api request failed (attempt {attempt}): {str(e)}")
                    raise

        raise Exception("Unexpected end of retry loop")

    async def get_stocks_report(
        self,
        api_key: str,
        nm_ids: List[int],
        limit: int = 250000,
        offset: int = 0,
        max_retries: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        ОДИН запрос к WB Seller Analytics API — остатки на складах WB по списку nmId.
        При 429 — ждёт 65 секунд и повторяет (до max_retries раз).
        """
        headers = {
            "Authorization": api_key,
            "Content-Type": "application/json"
        }
        body = {
            "nmIds": nm_ids,
            "limit": limit,
            "offset": offset,
        }

        ssl_context = ssl.create_default_context(cafile=certifi.where())

        for attempt in range(1, max_retries + 1):
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            try:
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.post(
                        f"{self.analytics_base_url}/analytics/v1/stocks-report/wb-warehouses",
                        headers=headers,
                        json=body,
                        timeout=aiohttp.ClientTimeout(total=65),
                    ) as response:

                        if response.status == 200:
                            data = await response.json()
                            items = data.get("data", {}).get("items", [])
                            logger.info(f"📥 Received {len(items)} stock rows for {len(nm_ids)} nmIds")
                            return items

                        elif response.status == 401:
                            raise Exception("Invalid API Key")

                        elif response.status == 429:
                            if attempt < max_retries:
                                logger.warning(
                                    f"⏳ Rate limit hit on stocks-report (attempt {attempt}/{max_retries}), "
                                    f"waiting {RATE_LIMIT_WAIT}s..."
                                )
                                await asyncio.sleep(RATE_LIMIT_WAIT)
                                continue
                            else:
                                raise Exception(
                                    f"Rate limit exceeded after {max_retries} retries"
                                )

                        else:
                            error_text = await response.text()
                            raise Exception(f"WB API error {response.status}: {error_text}")

            except Exception as e:
                if "Rate limit" not in str(e) or attempt >= max_retries:
                    logger.error(f"WB stocks-report request failed (attempt {attempt}): {str(e)}")
                    raise

        raise Exception("Unexpected end of retry loop")
