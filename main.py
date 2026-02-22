"""Polymarket Trader V2 - 主入口"""

import logging
import sys
from pathlib import Path

from src.config import Config
from src.storage import Storage
from src.web import WebApp


def setup_logging(log_dir: str = "logs", level: str = "INFO"):
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(f"{log_dir}/trader.log"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main():
    config = Config.from_file("data/config.json")
    setup_logging(config.log_dir, config.log_level)

    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Polymarket Trader V2 启动")
    logger.info("=" * 60)

    storage = Storage("data")

    app = WebApp(config, storage)
    app.run()


if __name__ == "__main__":
    main()
