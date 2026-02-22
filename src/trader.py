"""交易核心逻辑 - 主循环、过滤、跟单、仓位管理"""

import asyncio
import logging
import time
from typing import Optional, Callable
from dataclasses import dataclass
from datetime import datetime

from src.config import Config
from src.storage import Storage
from src.api_client import APIClient, Activity

logger = logging.getLogger(__name__)


@dataclass
class TraderState:
    is_running: bool = False
    start_time: Optional[datetime] = None
    success_count: int = 0
    error_message: str = ""


class PolymarketTrader:
    def __init__(self, config: Config, storage: Storage):
        self.config = config
        self.storage = storage
        self.state = TraderState()
        self._stop_event = asyncio.Event()

    async def start(self):
        if self.state.is_running:
            logger.warning("Trader 已在运行中")
            return

        logger.info("=" * 60)
        logger.info("Polymarket 跟单机器人启动")
        logger.info(f"交易钱包: {self.config.trading_wallet}")
        logger.info(f"监控目标: {self.config.target_wallet}")
        logger.info(f"跟单比例: {self.config.percentage * 100}%")
        logger.info(f"交易模式: {self.config.trade_mode}")
        logger.info(f"每日上限: {self.config.max_trades}")
        logger.info(f"检查间隔: {self.config.interval}秒")
        logger.info("=" * 60)

        self.state.is_running = True
        self.state.start_time = datetime.now()
        self.state.success_count = self.storage.get_today_success_count()
        self._stop_event.clear()

        try:
            async with APIClient(self.config) as api:
                while self.state.is_running and not self._stop_event.is_set():
                    try:
                        await self._check_and_trade(api)
                    except Exception as e:
                        logger.error(f"交易循环出错: {e}", exc_info=True)
                        self.state.error_message = str(e)

                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(), timeout=self.config.interval
                        )
                    except asyncio.TimeoutError:
                        continue
        finally:
            self.state.is_running = False
            logger.info("交易机器人已停止")

    def stop(self):
        logger.info("正在停止交易机器人...")
        self.state.is_running = False
        self._stop_event.set()

    async def _check_and_trade(self, api: APIClient):
        """步骤1: 获取目标钱包活动"""
        activities = await api.get_activity(self.config.target_wallet, limit=10)
        logger.info(f"获取到 {len(activities)} 条活动记录")

        now_ts = int(time.time())
        time_window = self.config.interval + 1
        processed_tokens = set()

        for activity in activities:
            # 步骤2: 对照 activity_list.json 查重
            existing = self.storage.find_activity(activity.timestamp, self.config.target_wallet)
            if existing:
                continue

            # 新记录 → 先写入 activity_list.json
            record = self._activity_to_record(activity)
            self.storage.add_activity(record)

            # 时间窗口检查: 交易时间是否在 interval+1 秒内
            if now_ts - activity.timestamp > time_window:
                self.storage.update_activity_status(
                    activity.timestamp, self.config.target_wallet,
                    "miss", reason="超过时间窗口"
                )
                logger.info(f"错过交易: {activity.title[:40]} (超时 {now_ts - activity.timestamp}s)")
                continue

            # 步骤3.1: 过滤检查
            filter_reason = self._check_filters(activity)
            if filter_reason:
                self.storage.update_activity_status(
                    activity.timestamp, self.config.target_wallet,
                    "filtered", reason=filter_reason
                )
                logger.info(f"过滤: {activity.title[:40]} - {filter_reason}")
                continue

            # 批次内 token 去重
            if activity.asset in processed_tokens:
                self.storage.update_activity_status(
                    activity.timestamp, self.config.target_wallet,
                    "filtered", reason="本批次重复token"
                )
                continue

            # 仓位检查: token 是否已有 open 仓位
            if self.storage.get_position_by_token(activity.asset):
                self.storage.update_activity_status(
                    activity.timestamp, self.config.target_wallet,
                    "filtered", reason="已有持仓（不加仓）"
                )
                logger.info(f"跳过: {activity.title[:40]} - 已有持仓")
                continue

            processed_tokens.add(activity.asset)

            # 步骤3.2: 执行交易
            await self._process_trade(api, activity)

    def _check_filters(self, activity: Activity) -> Optional[str]:
        """步骤3.1: 过滤检查，返回不通过的原因，None 表示通过"""
        if activity.trade_type != "TRADE":
            return f"非交易类型: {activity.trade_type}"

        if self.config.trade_mode == "buy" and activity.side != "BUY":
            return f"模式=只跟买, 跳过 {activity.side}"
        elif self.config.trade_mode == "sell" and activity.side != "SELL":
            return f"模式=只跟卖, 跳过 {activity.side}"

        # 日亏损检查 (通过 PnL API 判断，这里简化为检查 storage 中的数据)
        # 实际的 PnL 在 web.py 的 /api/pnl 中计算

        # 每日交易上限
        today_count = self.storage.get_today_success_count()
        if today_count >= self.config.max_trades:
            return f"达到每日上限 {self.config.max_trades}"

        return None

    async def _process_trade(self, api: APIClient, activity: Activity):
        """步骤3.2: 处理单笔交易"""
        logger.info(f"处理交易: {activity.title[:40]}")
        logger.info(f"  目标: {activity.size:.4f} tokens @ ${activity.price:.4f} = ${activity.usdc_size:.2f}")

        # 计算跟单金额
        follow_size = activity.size * self.config.percentage
        follow_usdc = follow_size * activity.price

        # 金额过滤
        if follow_usdc < self.config.min_amount:
            self.storage.update_activity_status(
                activity.timestamp, self.config.target_wallet,
                "filtered", reason=f"金额 ${follow_usdc:.2f} < 最小 ${self.config.min_amount}",
                follow_size=follow_size, follow_usdc=follow_usdc,
            )
            logger.info(f"  金额过小: ${follow_usdc:.2f} < ${self.config.min_amount}")
            return

        if follow_usdc > self.config.max_amount:
            logger.info(f"  金额超限: ${follow_usdc:.2f} > ${self.config.max_amount}, 调整")
            follow_usdc = self.config.max_amount
            follow_size = follow_usdc / activity.price

        # 滑点 + 深度检查
        passed, msg, order_price, adjusted_size = await api.check_slippage(
            activity.asset, activity.price, follow_size
        )
        logger.info(f"  滑点检查: {msg}")

        if not passed:
            self.storage.update_activity_status(
                activity.timestamp, self.config.target_wallet,
                "filtered", reason=f"滑点: {msg}",
                follow_size=follow_size, follow_price=order_price,
                follow_usdc=follow_usdc,
            )
            return

        follow_size = adjusted_size
        follow_usdc = follow_size * order_price

        logger.info(f"  跟单: {follow_size:.4f} tokens @ ${order_price:.4f} = ${follow_usdc:.2f}")

        # 发送交易 (内部已包含 5 次重试)
        result = await api.send_trade(
            token_id=activity.asset,
            size=follow_size,
            price=order_price,
            side=activity.side,
            trading_wallet=self.config.trading_wallet,
            target_wallet=self.config.target_wallet,
        )

        if result["success"]:
            order_id = result.get("order_id", "")
            logger.info(f"  跟单成功: {order_id}")

            self.storage.update_activity_status(
                activity.timestamp, self.config.target_wallet,
                "success",
                follow_size=follow_size, follow_price=order_price,
                follow_usdc=follow_usdc, order_id=order_id,
            )

            # 记录仓位
            self.storage.add_position({
                "token_id": activity.asset,
                "market_title": activity.title,
                "outcome": activity.outcome,
                "side": activity.side,
                "entry_price": order_price,
                "entry_usdc": follow_usdc,
                "size": follow_size,
            })

            self.state.success_count += 1
        else:
            error = result.get("error", "未知错误")
            logger.error(f"  跟单失败: {error}")

            self.storage.update_activity_status(
                activity.timestamp, self.config.target_wallet,
                "failed",
                follow_size=follow_size, follow_price=order_price,
                follow_usdc=follow_usdc, error_msg=error,
            )

    def _activity_to_record(self, activity: Activity) -> dict:
        return {
            "timestamp": activity.timestamp,
            "target_wallet": self.config.target_wallet,
            "market_title": activity.title,
            "token_id": activity.asset,
            "side": activity.side,
            "outcome": activity.outcome,
            "target_size": activity.size,
            "target_price": activity.price,
            "target_usdc": activity.usdc_size,
            "follow_size": 0,
            "follow_price": 0,
            "follow_usdc": 0,
            "status": "pending",
            "order_id": "",
            "error_msg": "",
        }

    def get_stats(self) -> dict:
        return {
            "is_running": self.state.is_running,
            "start_time": self.state.start_time.isoformat() if self.state.start_time else None,
            "success": self.state.success_count,
            "error": self.state.error_message,
        }
