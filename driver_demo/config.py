"""Config sourced from environment variables — matches `hub`'s
`docker-compose.yml` `driver-demo:` service block.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int
    username: str | None
    password: str | None


@dataclass(frozen=True)
class AppConfig:
    mqtt: MqttConfig
    scenario_dir: Path


def load_config() -> AppConfig:
    return AppConfig(
        mqtt=MqttConfig(
            host=os.environ.get("MQTT_HOST", "mosquitto"),
            port=int(os.environ.get("MQTT_PORT", "1883")),
            username=os.environ.get("MQTT_USERNAME") or None,
            password=os.environ.get("MQTT_PASSWORD") or None,
        ),
        scenario_dir=Path(os.environ.get("DEMO_SCENARIO_DIR", "/app/scenarios")),
    )
