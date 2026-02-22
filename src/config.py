"""配置管理模块"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    trading_wallet: str = ""
    target_wallet: str = ""
    percentage: float = 1.0
    interval: int = 5
    max_trades: int = 10
    slippage_protection: float = 0.05
    min_amount: float = 2.0
    max_amount: float = 500.0
    max_daily_loss: float = 200.0
    trade_mode: str = "buy"
    trade_api_url: str = "http://205.198.88.212:8081/trade"
    http_timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    log_dir: str = "logs"
    log_level: str = "INFO"
    web_host: str = "0.0.0.0"
    web_port: int = 8000

    @classmethod
    def from_file(cls, path: str) -> "Config":
        config_path = Path(path)
        if config_path.exists():
            with open(config_path, "r") as f:
                data = json.load(f)
            return cls(
                **{k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            )
        return cls()

    def to_file(self, path: str):
        config_path = Path(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def to_dict(self) -> dict:
        return {
            "trading_wallet": self.trading_wallet,
            "target_wallet": self.target_wallet,
            "percentage": self.percentage,
            "interval": self.interval,
            "max_trades": self.max_trades,
            "slippage_protection": self.slippage_protection,
            "min_amount": self.min_amount,
            "max_amount": self.max_amount,
            "max_daily_loss": self.max_daily_loss,
            "trade_mode": self.trade_mode,
            "trade_api_url": self.trade_api_url,
            "web_host": self.web_host,
            "web_port": self.web_port,
        }

    def validate(self) -> tuple[bool, str]:
        if not self.trading_wallet:
            return False, "trading_wallet is required"
        if not self.target_wallet:
            return False, "target_wallet is required"
        if not (0 < self.percentage <= 1):
            return False, "percentage must be between 0 and 1"
        if self.interval < 1:
            return False, "interval must be at least 1 second"
        if self.max_trades < 1:
            return False, "max_trades must be at least 1"
        if self.min_amount <= 0:
            return False, "min_amount must be positive"
        if self.max_amount < self.min_amount:
            return False, "max_amount must be >= min_amount"
        return True, "OK"
