"""Human-owned configuration; never editable through model tools."""

import json
import re
from dataclasses import dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit


class LabError(Exception):
    """Expected error safe to display to the operator."""


@dataclass(frozen=True)
class Config:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3.5:27b-q4_K_M"
    num_ctx: int = 8192
    num_predict: int = 2048
    timeout_seconds: int = 180
    max_steps: int = 6
    max_tool_calls: int = 12
    max_file_bytes: int = 8192
    max_history_bytes: int = 32768
    think: bool = False

    def __post_init__(self):
        try:
            u = urlsplit(self.base_url)
            port = u.port
        except (ValueError, TypeError, AttributeError) as exc:
            raise LabError("base_url 格式错误") from exc
        if (u.scheme != "http" or u.hostname not in {"127.0.0.1", "::1"}
                or u.username is not None or u.password is not None
                or u.path not in {"", "/"} or u.query or u.fragment
                or port is None or not 1 <= port <= 65535):
            raise LabError("只允许 http://127.0.0.1:端口 或 http://[::1]:端口")
        if (not isinstance(self.model, str)
                or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", self.model)
                or "cloud" in self.model.lower()):
            raise LabError("model 必须是本地模型名称，禁止 cloud 模型")
        limits = {
            "num_ctx": (4096, 32768), "num_predict": (128, 4096),
            "timeout_seconds": (1, 600), "max_steps": (1, 12),
            "max_tool_calls": (1, 24), "max_file_bytes": (256, 16384),
            "max_history_bytes": (4096, 65536),
        }
        for name, (low, high) in limits.items():
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise LabError(f"{name} 必须是 {low}..{high} 的整数")
        if self.num_predict >= self.num_ctx // 2:
            raise LabError("num_predict 必须小于 num_ctx 的一半")
        if type(self.think) is not bool:
            raise LabError("think 必须是布尔值")

    @classmethod
    def load(cls, path: Path):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)}:
                raise LabError("配置必须是 JSON 对象，且不能含未知字段")
            return cls(**data)
        except (OSError, ValueError, TypeError) as exc:
            raise LabError(f"无法读取配置 {path.name}；先复制 config.example.json。{exc}") from exc
