"""API 客户端 - 仅封装 4 个外部 API"""

import asyncio
import logging
from typing import Optional
from dataclasses import dataclass

import httpx

from src.config import Config

logger = logging.getLogger(__name__)

ACTIVITY_API = "https://data-api.polymarket.com/activity"
BOOK_API = "https://clob.polymarket.com/book"
MIDPOINT_API = "https://clob.polymarket.com/midpoint"


@dataclass
class Activity:
    timestamp: int
    tx_hash: str
    trade_type: str
    side: str
    title: str
    outcome: str
    size: float
    usdc_size: float
    price: float
    asset: str


class APIClient:
    def __init__(self, config: Config):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.config.http_timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs) -> Optional[httpx.Response]:
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = await self._client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                logger.warning(f"请求失败 (第{attempt + 1}次): {url} - {e}")
                last_error = e
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay * (attempt + 1))
        logger.error(f"所有重试失败: {url} - {last_error}")
        return None

    # ========== 1. Activity API ==========

    async def get_activity(self, wallet: str, limit: int = 10) -> list[Activity]:
        response = await self._request(
            "GET", ACTIVITY_API,
            params={
                "limit": limit,
                "sortBy": "TIMESTAMP",
                "sortDirection": "DESC",
                "user": wallet.lower(),
            },
        )
        if not response:
            return []

        activities = []
        for item in response.json():
            try:
                activities.append(Activity(
                    timestamp=int(item.get("timestamp", 0)),
                    tx_hash=item.get("transactionHash", ""),
                    trade_type=item.get("type", ""),
                    side=item.get("side", ""),
                    title=item.get("title", ""),
                    outcome=item.get("outcome", ""),
                    size=float(item.get("size", 0)),
                    usdc_size=float(item.get("usdcSize", 0)),
                    price=float(item.get("price", 0)),
                    asset=item.get("asset", ""),
                ))
            except (ValueError, TypeError) as e:
                logger.warning(f"解析活动失败: {e}")
        return activities

    # ========== 2. Order Book API (滑点检查) ==========

    async def check_slippage(
        self, token_id: str, target_price: float, follow_size: float
    ) -> tuple[bool, str, float, float]:
        """
        滑点 + 深度检查。
        返回 (可交易, 消息, order_price, adjusted_follow_size)
        """
        if not token_id or not target_price:
            return True, "无数据", target_price, follow_size

        order_price = target_price * (1 + self.config.slippage_protection)

        response = await self._request("GET", BOOK_API, params={"token_id": token_id})
        if not response:
            return True, "无订单簿数据", order_price, follow_size

        try:
            order_book = response.json()
            asks = order_book.get("asks", [])

            available_depth = 0.0
            for ask in asks:
                ask_price = float(ask.get("price", 0))
                ask_size = float(ask.get("size", 0))
                if ask_price >= order_price:
                    available_depth += ask_size

            if available_depth <= 0:
                return False, "无可用深度（无 ask >= 下单价格）", order_price, 0

            adjusted_size = min(follow_size, available_depth)
            msg = f"深度 {available_depth:.2f}, 下单价 {order_price:.4f}"
            if adjusted_size < follow_size:
                msg += f", 缩减 {follow_size:.2f} → {adjusted_size:.2f}"

            return True, msg, order_price, adjusted_size
        except Exception as e:
            logger.warning(f"解析订单簿失败: {e}")
            return True, "解析失败", order_price, follow_size

    # ========== 3. Midpoint API (PnL 价格) ==========

    async def get_token_price(self, token_id: str) -> Optional[float]:
        if not token_id:
            return None

        response = await self._request(
            "GET", MIDPOINT_API, params={"token_id": token_id}
        )
        if response and response.status_code == 200:
            try:
                data = response.json()
                if isinstance(data, dict) and "mid" in data:
                    return float(data["mid"])
            except Exception:
                pass

        # fallback: 从订单簿计算中间价
        response = await self._request("GET", BOOK_API, params={"token_id": token_id})
        if response and response.status_code == 200:
            try:
                data = response.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                bid_prices = [float(b["price"]) for b in bids if float(b.get("price", 0)) > 0]
                ask_prices = [float(a["price"]) for a in asks if float(a.get("price", 0)) > 0]
                best_bid = max(bid_prices) if bid_prices else 0
                best_ask = min(ask_prices) if ask_prices else 0
                if best_bid and best_ask:
                    return (best_bid + best_ask) / 2
                return best_bid or best_ask or None
            except Exception:
                pass

        return None

    # ========== 4. Trade API ==========

    async def send_trade(
        self, token_id: str, size: float, price: float,
        side: str, trading_wallet: str, target_wallet: str,
    ) -> dict:
        order = {
            "side": side,
            "token_id": token_id,
            "size": round(size, 4),
            "price": round(price, 4),
            "trading_wallet": trading_wallet,
            "target_wallet": target_wallet,
        }

        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                response = await self._client.post(
                    self.config.trade_api_url, json=order, timeout=60
                )
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"交易API响应 (第{attempt}次): {result}")
                    if result.get("response", {}).get("success"):
                        return {
                            "success": True,
                            "order_id": result["response"].get("orderID", ""),
                        }
                    error = result.get("error", "未知错误")
                    if attempt == max_attempts:
                        return {"success": False, "error": error}
                    logger.warning(f"交易未成功 (第{attempt}次): {error}")
                else:
                    error = response.text
                    if attempt == max_attempts:
                        return {"success": False, "error": f"HTTP {response.status_code}: {error}"}
                    logger.warning(f"交易HTTP错误 (第{attempt}次): {response.status_code}")
            except Exception as e:
                if attempt == max_attempts:
                    return {"success": False, "error": str(e)}
                logger.warning(f"交易异常 (第{attempt}次): {e}")

            await asyncio.sleep(1 * attempt)

        return {"success": False, "error": "重试耗尽"}
