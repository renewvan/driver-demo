"""The shared Demo mode switch: `renewvan-demo/enabled` (state, retained) and
`renewvan-demo/enabled/set` (command), the same `<topic>` / `<topic>/set` convention as the kiosk
settings. Any client can publish the command, so toggling demo mode in one dashboard starts the
simulated van for every other client; node-demo itself always runs and is idle while disabled.

Threading: commands arrive on paho's network thread, which is also the thread that receives the
broker's acknowledgements. Waiting for those acks there deadlocks, so `on_command` only records
the request and the driver thread (the 1 Hz `tick`) applies it.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from typing import Protocol

from node_demo.scenario import Scenario, messages_at

logger = logging.getLogger(__name__)

ENABLED_TOPIC = "renewvan-demo/enabled"
ENABLED_SET_TOPIC = "renewvan-demo/enabled/set"
ROUTER_HEALTH_TOPIC = "renewvan-demo/router/health"


class PublisherLike(Protocol):
    def publish(self, topic: str, payload: object) -> None: ...
    def publish_raw(self, topic: str, payload: str) -> None: ...
    def clear(self, topic: str) -> None: ...
    def flush(self, timeout: float = ...) -> bool: ...


def parse_enabled(payload: str) -> bool | None:
    """A JSON boolean, exactly like every other bus payload; anything else is not a command."""
    if payload == "true":
        return True
    if payload == "false":
        return False
    return None


class Controller:
    def __init__(self, scenarios: Sequence[Scenario], publisher: PublisherLike) -> None:
        self._scenarios = list(scenarios)
        self._publisher = publisher
        self._enabled = False
        self._lock = threading.RLock()
        # The driver tick at which the demo was last enabled; scenarios loop relative to it.
        self._origin = 0
        self._published: set[str] = set()
        # Latest requested state not yet applied; a later command replaces an earlier one.
        self._pending: bool | None = None
        self._wake: Callable[[], None] = lambda: None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_waker(self, wake: Callable[[], None]) -> None:
        """Called after a command is queued so the driver applies it now, not up to 1 s later."""
        self._wake = wake

    def start(self, retained_enabled: bool = False) -> None:
        """Boot. A retained `true` resumes the demo from its initial state: a crash can leave
        retained topics mid-loop on the broker, and the first tick republishes every property."""
        with self._lock:
            self._publisher.publish(ENABLED_TOPIC, retained_enabled)
            if retained_enabled:
                self._enable(0)

    def on_command(self, payload: str) -> None:
        """MQTT thread: record the request only, never wait for the broker here."""
        value = parse_enabled(payload)
        if value is None:
            logger.warning("Ignoring invalid %s payload %r", ENABLED_SET_TOPIC, payload)
            return
        with self._lock:
            self._pending = value
        self._wake()

    def set_enabled(self, enabled: bool, now_tick: int = 0) -> None:
        """Driver thread (or boot): apply a state change, publishing and clearing as needed."""
        with self._lock:
            if enabled != self._enabled:
                if enabled:
                    self._enable(now_tick)
                else:
                    self._disable()
                logger.info("Demo mode %s", "enabled" if enabled else "disabled")
            # Re-asserted even when unchanged: harmless, and it repairs a lost retained flag.
            self._publisher.publish(ENABLED_TOPIC, enabled)

    def apply_pending(self, now_tick: int) -> bool:
        """Apply a queued command, if any, starting the scenarios at `now_tick`. Returns whether
        one was applied. Driver thread only."""
        with self._lock:
            pending, self._pending = self._pending, None
            if pending is None:
                return False
            self.set_enabled(pending, now_tick=now_tick)
            return True

    def tick(self, n: int) -> None:
        """One scenario second. `n` is the driver's absolute tick. A queued command is applied
        first and starts every scenario at its beginning, whatever tick it arrived on."""
        with self._lock:
            if self.apply_pending(n):
                return
            if self._enabled:
                self._publish_tick(max(0, n - self._origin))

    def shutdown(self) -> None:
        """Clear the simulated van; the retained `enabled` flag stays so the next boot resumes."""
        with self._lock:
            self._clear_van()
            self._enabled = False

    def _enable(self, now_tick: int) -> None:
        self._enabled = True
        self._origin = now_tick
        self._publish_tick(0)
        if any(s.entity == "router" for s in self._scenarios):
            self._publisher.publish_raw(ROUTER_HEALTH_TOPIC, "online")
            self._published.add(ROUTER_HEALTH_TOPIC)

    def _disable(self) -> None:
        self._enabled = False
        self._clear_van()

    def _clear_van(self) -> None:
        for topic in sorted(self._published):
            self._publisher.clear(topic)
        self._published.clear()
        self._publisher.flush()

    def _publish_tick(self, relative: int) -> None:
        for scenario in self._scenarios:
            for topic, value in messages_at(scenario, relative).items():
                self._publisher.publish(topic, value)
                self._published.add(topic)
