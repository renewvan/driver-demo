"""1 Hz scenario driver: every scenario shares one clock so entities stay coherent."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Protocol, Sequence

from node_demo.scenario import Scenario, messages_at

logger = logging.getLogger(__name__)

ROUTER_HEALTH_TOPIC = "renewvan-demo/router/health"


class PublisherLike(Protocol):
    def publish(self, topic: str, payload: object) -> None: ...
    def publish_raw(self, topic: str, payload: str) -> None: ...
    def clear(self, topic: str) -> None: ...
    def mark_offline(self) -> None: ...
    def flush(self, timeout: float = ...) -> bool: ...
    def disconnect(self) -> None: ...


class Driver:
    def __init__(
        self,
        scenarios: Sequence[Scenario],
        publisher: PublisherLike,
        stop: threading.Event | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._scenarios = list(scenarios)
        self._publisher = publisher
        self._stop = stop or threading.Event()
        self._clock = clock
        self._published: set[str] = set()

    def stop(self) -> None:
        self._stop.set()

    def tick(self, n: int) -> None:
        for scenario in self._scenarios:
            for topic, value in messages_at(scenario, n).items():
                self._publisher.publish(topic, value)
                self._published.add(topic)

    def _announce_router_health(self) -> None:
        """The real router node publishes `renewvan/router/health`, and the dashboard's uplink
        reads it from the demo root too; a simulated router must look alive, like a real one."""
        if any(s.entity == "router" for s in self._scenarios):
            self._publisher.publish_raw(ROUTER_HEALTH_TOPIC, "online")
            self._published.add(ROUTER_HEALTH_TOPIC)

    def run(self) -> None:
        """Publish the initial state, tick once per second until stopped, then clean up.

        Tick `n` is due at `start + n` on the monotonic clock, so sleeping to that absolute
        deadline never accumulates drift; if a tick runs late, missed ticks are replayed
        back to back rather than skipped.
        """
        start = self._clock()
        try:
            self.tick(0)
            self._announce_router_health()
            logger.info("Published initial state of %d scenarios", len(self._scenarios))
            n = 1
            while not self._stop.wait(max(0.0, start + n - self._clock())):
                self.tick(n)
                n += 1
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Clear every retained topic published, wait for the broker to ack, then go offline."""
        for topic in sorted(self._published):
            self._publisher.clear(topic)
        self._publisher.flush()
        self._publisher.mark_offline()
        self._publisher.flush()
        self._publisher.disconnect()
        logger.info("Cleared %d retained topics and went offline", len(self._published))
        self._published.clear()
