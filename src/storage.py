"""JSON 文件存储层 - 管理 activity_list.json 和 position.json"""

import json
import threading
from datetime import datetime, date
from pathlib import Path
from typing import Optional


class Storage:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.activity_path = self.data_dir / "activity_list.json"
        self.position_path = self.data_dir / "position.json"
        self._lock = threading.Lock()

    # ========== Activity List ==========

    def load_activities(self) -> list[dict]:
        with self._lock:
            return self._read_json(self.activity_path, [])

    def save_activities(self, activities: list[dict]):
        with self._lock:
            self._write_json(self.activity_path, activities)

    def find_activity(self, timestamp: int, target_wallet: str) -> Optional[dict]:
        activities = self.load_activities()
        for a in activities:
            if a.get("timestamp") == timestamp and a.get("target_wallet") == target_wallet:
                return a
        return None

    def add_activity(self, activity: dict):
        """添加一条活动记录"""
        activities = self.load_activities()
        activity["created_at"] = datetime.now().isoformat()
        activities.append(activity)
        self.save_activities(activities)

    def update_activity_status(self, timestamp: int, target_wallet: str, status: str, **extra):
        """更新活动记录的状态和附加字段"""
        activities = self.load_activities()
        for a in activities:
            if a.get("timestamp") == timestamp and a.get("target_wallet") == target_wallet:
                a["status"] = status
                a["updated_at"] = datetime.now().isoformat()
                for k, v in extra.items():
                    a[k] = v
                break
        self.save_activities(activities)

    def get_today_success_count(self) -> int:
        today_str = date.today().isoformat()
        activities = self.load_activities()
        count = 0
        for a in activities:
            if a.get("status") == "success":
                created = a.get("created_at", "")
                if created.startswith(today_str):
                    count += 1
        return count

    # ========== Position List ==========

    def load_positions(self) -> list[dict]:
        with self._lock:
            return self._read_json(self.position_path, [])

    def save_positions(self, positions: list[dict]):
        with self._lock:
            self._write_json(self.position_path, positions)

    def get_open_positions(self) -> list[dict]:
        return [p for p in self.load_positions() if p.get("status") == "open"]

    def get_position_by_token(self, token_id: str) -> Optional[dict]:
        for p in self.load_positions():
            if p.get("token_id") == token_id and p.get("status") == "open":
                return p
        return None

    def add_position(self, position: dict):
        positions = self.load_positions()
        position["status"] = "open"
        position["opened_at"] = datetime.now().isoformat()
        positions.append(position)
        self.save_positions(positions)

    def get_today_positions(self) -> list[dict]:
        """获取今日开仓的仓位"""
        today_str = date.today().isoformat()
        return [
            p for p in self.load_positions()
            if p.get("status") == "open" and p.get("opened_at", "").startswith(today_str)
        ]

    # ========== Clear ==========

    def clear_all(self):
        self.save_activities([])
        self.save_positions([])

    # ========== Internal ==========

    def _read_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return default

    def _write_json(self, path: Path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
