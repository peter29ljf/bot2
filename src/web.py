"""Flask Web 服务"""

import asyncio
import logging
import os
import threading

from flask import Flask, render_template, jsonify, request, Response

from src.config import Config
from src.storage import Storage
from src.trader import PolymarketTrader
from src.api_client import APIClient

logger = logging.getLogger(__name__)


class WebApp:
    def __init__(self, config: Config, storage: Storage):
        self.config = config
        self.storage = storage
        self.trader: PolymarketTrader = None

        template_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "templates")
        )
        self.app = Flask(__name__, template_folder=template_dir)
        self._setup_routes()

    def _setup_routes(self):

        @self.app.route("/")
        def index():
            return render_template("index.html")

        @self.app.route("/api/status")
        def api_status():
            stats = (
                self.trader.get_stats()
                if self.trader
                else {"is_running": False, "start_time": None, "success": 0, "error": ""}
            )
            return jsonify({
                "running": stats["is_running"],
                "config": self.config.to_dict(),
                "stats": {
                    "success": stats["success"],
                    "start_time": stats["start_time"],
                    "last_error": stats["error"],
                },
            })

        @self.app.route("/api/config", methods=["GET", "POST"])
        def api_config():
            if request.method == "POST":
                data = request.json
                self.config.trading_wallet = data.get("trading_wallet", self.config.trading_wallet)
                self.config.target_wallet = data.get("target_wallet", self.config.target_wallet)
                self.config.percentage = float(data.get("percentage", self.config.percentage))
                self.config.interval = int(data.get("interval", self.config.interval))
                self.config.max_trades = int(data.get("max_trades", self.config.max_trades))
                self.config.slippage_protection = float(data.get("slippage_protection", self.config.slippage_protection))
                self.config.min_amount = float(data.get("min_amount", self.config.min_amount))
                self.config.max_amount = float(data.get("max_amount", self.config.max_amount))
                self.config.trade_mode = data.get("trade_mode", self.config.trade_mode)
                self.config.max_daily_loss = float(data.get("max_daily_loss", self.config.max_daily_loss))
                self.config.to_file("data/config.json")
                return jsonify({"success": True, "config": self.config.to_dict()})
            return jsonify(self.config.to_dict())

        @self.app.route("/api/start", methods=["POST"])
        def api_start():
            if self.trader and self.trader.state.is_running:
                return jsonify({"success": False, "error": "已在运行中"})

            valid, msg = self.config.validate()
            if not valid:
                return jsonify({"success": False, "error": msg})

            self.trader = PolymarketTrader(self.config, self.storage)

            def run_trader():
                asyncio.run(self.trader.start())

            thread = threading.Thread(target=run_trader, daemon=True)
            thread.start()
            return jsonify({"success": True})

        @self.app.route("/api/stop", methods=["POST"])
        def api_stop():
            if not self.trader or not self.trader.state.is_running:
                return jsonify({"success": False, "error": "未运行"})
            self.trader.stop()
            return jsonify({"success": True})

        @self.app.route("/api/wallets")
        def api_wallets():
            """从本地 position.json + activity API 获取信息"""
            open_positions = self.storage.get_open_positions()

            async def get_target_activity():
                async with APIClient(self.config) as api:
                    acts = await api.get_activity(self.config.target_wallet, limit=5)
                    return [
                        {
                            "timestamp": a.timestamp,
                            "title": a.title,
                            "type": a.trade_type,
                            "side": a.side,
                            "size": a.size,
                            "usdcSize": a.usdc_size,
                            "outcome": a.outcome,
                        }
                        for a in acts
                    ]

            try:
                target_activity = asyncio.run(get_target_activity())
            except Exception as e:
                logger.error(f"获取目标活动失败: {e}")
                target_activity = []

            return jsonify({
                "positions_count": len(open_positions),
                "positions": open_positions,
                "target_activity": target_activity,
            })

        @self.app.route("/api/trades")
        def api_trades():
            """返回 activity_list.json 数据"""
            activities = self.storage.load_activities()
            activities.sort(key=lambda a: a.get("timestamp", 0), reverse=True)
            limit = request.args.get("limit", 50, type=int)
            return jsonify(activities[:limit])

        @self.app.route("/api/pnl")
        def api_pnl():
            """从 position.json + midpoint API 计算持仓盈亏"""
            open_positions = self.storage.get_open_positions()

            async def calc_pnl():
                async with APIClient(self.config) as api:
                    total_pnl = 0.0
                    total_cost = 0.0
                    enriched = []
                    for pos in open_positions:
                        entry_price = pos.get("entry_price", 0)
                        size = pos.get("size", 0)
                        entry_usdc = pos.get("entry_usdc", 0)
                        total_cost += entry_usdc
                        current_price = await api.get_token_price(pos.get("token_id", ""))
                        pnl = 0.0
                        if current_price and entry_price:
                            pnl = (current_price - entry_price) * size
                        total_pnl += pnl
                        enriched.append({
                            **pos,
                            "current_price": current_price,
                            "pnl": round(pnl, 4),
                        })
                    return total_pnl, total_cost, enriched

            try:
                total_pnl, total_cost, enriched_positions = asyncio.run(calc_pnl())
                return jsonify({
                    "total_pnl": round(total_pnl, 2),
                    "total_cost": round(total_cost, 2),
                    "open_positions": len(open_positions),
                    "positions": enriched_positions,
                })
            except Exception as e:
                logger.error(f"计算盈亏失败: {e}")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/api/logs")
        def api_logs():
            def generate():
                try:
                    with open("logs/trader.log", "r") as f:
                        lines = f.readlines()[-100:]
                        for line in lines:
                            yield f"data: {line}\n\n"
                except Exception:
                    yield "data: No logs available\n\n"
            return Response(generate(), mimetype="text/event-stream")

        @self.app.route("/api/clear", methods=["POST"])
        def api_clear():
            try:
                if self.trader and self.trader.state.is_running:
                    self.trader.stop()
                    import time
                    time.sleep(2)
                self.storage.clear_all()
                return jsonify({"success": True, "message": "所有数据已清理"})
            except Exception as e:
                logger.error(f"清理数据失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

    def run(self, host=None, port=None):
        host = host or self.config.web_host
        port = port or self.config.web_port
        logger.info(f"启动Web服务: http://{host}:{port}")
        self.app.run(host=host, port=port, debug=False, use_reloader=False)
