"""Validated single-instance operating limits shared by adapters and deployment."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeSettings:
    answer_workers: int = 4
    answer_capacity: int = 16
    answer_timeout: float = 45
    user_requests_per_minute: int = 6
    shutdown_grace: float = 30
    health_host: str = "127.0.0.1"
    health_port: int = 8080
    export_workers: int = 2
    export_timeout: float = 120
    export_max_rows: int = 5000
    export_max_scanned: int = 20000
    export_max_bytes: int = 8 * 1024 * 1024

    def __post_init__(self):
        for name, value in vars(self).items():
            if name == "health_host":
                if not isinstance(value, str) or not value:
                    raise ValueError("runtime.health_host must be a nonempty host")
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"runtime.{name} must be a finite number")
            if name not in {
                "answer_timeout",
                "shutdown_grace",
                "export_timeout",
            } and not isinstance(value, int):
                raise ValueError(f"runtime.{name} must be an integer")
        if self.answer_workers < 1 or self.answer_capacity < self.answer_workers:
            raise ValueError("answer_capacity must be >= answer_workers >= 1")
        for name in (
            "answer_timeout",
            "user_requests_per_minute",
            "shutdown_grace",
            "health_port",
            "export_workers",
            "export_timeout",
            "export_max_rows",
            "export_max_scanned",
            "export_max_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"runtime.{name} must be positive")
        if self.health_port > 65535:
            raise ValueError("Invalid health port")

    @classmethod
    def parse(cls, values=None):
        values = values or {}
        if not isinstance(values, dict):
            raise ValueError("runtime must be a mapping")
        unknown = set(values) - cls.__dataclass_fields__.keys()
        if unknown:
            raise ValueError(f"Unknown runtime settings: {sorted(unknown)}")
        result = dict(values)
        if "HEALTH_HOST" in os.environ:
            result["health_host"] = os.environ["HEALTH_HOST"]
        if "HEALTH_PORT" in os.environ:
            result["health_port"] = int(os.environ["HEALTH_PORT"])
        return cls(**result)
