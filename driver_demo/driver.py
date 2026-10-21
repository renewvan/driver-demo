"""1 Hz clock: every scenario shares one tick so entities stay coherent. What is published, and
whether anything is, is the `Controller`'s call; the driver keeps time, applies queued commands
promptly, and shuts down in order.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger(__name__)


class ControllerLike(Protocol):
    def tick(self, n: int) -> None: ...
    def apply_pending(self, now_tick: int) -> bool: ...
    def shutdown(self) -> None: ...


class PublisherLike(Protocol):
    def mark_offline(self) -> None: ...
    def flush(self, timeout: float = ...) -> bool: ...
    def disconnect(self) -> None: ...


class Driver:
    def __init__(
        self,
        controller: ControllerLike,
        publisher: PublisherLike,
        stop: threading.Event | None = None,
        clock: Callable[[], float] = time.monotonic,
        wake: threading.Event | None = None,
    ) -> None:
        self._controller = controller
        self._publisher = publisher
        self._stop = stop or threading.Event()
        self._clock = clock
        # Set by the MQTT thread when a command is queued, so it is applied now, not on the next
        # second. Waking applies the command only: it must not consume a scenario tick.
        self._wake = wake or threading.Event()

    @property
    def wake(self) -> threading.Event:
        return self._wake

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def run(self) -> None:
        """Tick once per second until stopped, then clean up.

        Tick `n` is due at `start + n` on the monotonic clock, so sleeping to that absolute
        deadline never accumulates drift; if a tick runs late, missed ticks are replayed
        back to back rather than skipped. A wake (a queued command) interrupts the sleep to
        apply the command, then goes back to waiting for the same deadline.
        """
        start = self._clock()
        try:
            n = 1
            while not self._stop.is_set():
                remaining = max(0.0, start + n - self._clock())
                if self._wake.wait(remaining):
                    self._wake.clear()
                    if not self._stop.is_set():
                        self._controller.apply_pending(n)
                    continue
                self._controller.tick(n)
                n += 1
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        """Clear the van (the controller waits for the broker's ack), then go offline."""
        self._controller.shutdown()
        self._publisher.mark_offline()
        self._publisher.flush()
        self._publisher.disconnect()
        logger.info("Cleared the simulated van and went offline")
