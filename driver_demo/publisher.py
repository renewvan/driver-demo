"""Persistent MQTT connection to the renewvan bus, publishing under the separate
`renewvan/demo/` namespace. Same encoding as driver-router's publisher (JSON value, retained,
QoS 1, LWT on the health topic) so consumers read demo data with the same code.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

import paho.mqtt.client as mqtt

from driver_demo.config import MqttConfig
from driver_demo.scenario import TOPIC_ROOT

logger = logging.getLogger(__name__)

HEALTH_TOPIC = f"{TOPIC_ROOT}/health"


class Publisher:
    def __init__(self, config: MqttConfig) -> None:
        self._config = config
        # Clean session: all state is in retained topics, and a persistent session would replay
        # any `/set` command queued while this device was down, flipping the demo on a restart.
        self._client = mqtt.Client(client_id="driver-demo", clean_session=True)
        if config.username:
            self._client.username_pw_set(config.username, config.password)
        self._client.will_set(HEALTH_TOPIC, payload="offline", qos=1, retain=True)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._pending: list[mqtt.MQTTMessageInfo] = []
        self._subscriptions: dict[str, Callable[[str], None]] = {}

    def _on_connect(self, client, userdata, flags, rc):  # noqa: ANN001
        if rc == 0:
            logger.info(
                "Connected to renewvan-bus MQTT broker %s:%s", self._config.host, self._config.port
            )
            client.publish(HEALTH_TOPIC, payload="online", qos=1, retain=True)
            for topic in self._subscriptions:
                client.subscribe(topic, qos=1)
        else:
            logger.error("Renewvan-bus MQTT connect failed with rc=%s", rc)

    def _on_message(self, client, userdata, msg):  # noqa: ANN001
        callback = self._subscriptions.get(msg.topic)
        if callback is None:
            return
        try:
            callback(msg.payload.decode("utf-8", errors="replace"))
        except Exception:
            logger.exception("Error handling message on topic %s", msg.topic)

    def subscribe(self, topic: str, callback: Callable[[str], None]) -> None:
        """Register a callback; (re)subscribed on every connect, so reconnects keep listening."""
        self._subscriptions[topic] = callback
        self._client.subscribe(topic, qos=1)

    def connect(self) -> None:
        """Connect and start the network loop on a background thread."""
        self._client.connect(self._config.host, self._config.port)
        self._client.loop_start()

    def publish(self, topic: str, payload: object) -> None:
        self._client.publish(topic, payload=json.dumps(payload), qos=1, retain=True)

    def publish_raw(self, topic: str, payload: str) -> None:
        """Retained, unencoded string: health topics are bare words (`online`)."""
        self._client.publish(topic, payload=payload, qos=1, retain=True)

    def clear(self, topic: str) -> None:
        """Remove a retained topic: an empty retained payload is the ADR 0008 'no value'."""
        self._pending.append(self._client.publish(topic, payload=b"", qos=1, retain=True))

    def mark_offline(self) -> None:
        """Retained `offline`. A clean disconnect does not fire the LWT, so say it explicitly."""
        self._pending.append(
            self._client.publish(HEALTH_TOPIC, payload="offline", qos=1, retain=True)
        )

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until every `clear`/`mark_offline` publish is acknowledged by the broker.

        Returns False if the deadline passed first. paho 1.x `wait_for_publish` has no
        timeout and blocks forever on a dead connection, so poll `is_published` instead.
        """
        deadline = time.monotonic() + timeout
        pending, self._pending = self._pending, []
        for info in pending:
            while not info.is_published():
                if time.monotonic() >= deadline:
                    logger.warning("Timed out waiting for MQTT publish acknowledgements")
                    return False
                time.sleep(0.01)
        return True

    def disconnect(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()
