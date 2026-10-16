#!/usr/bin/env python3
"""node-demo entrypoint."""

from __future__ import annotations

import argparse
import logging
import signal
import threading

from node_demo.config import load_config
from node_demo.controller import ENABLED_SET_TOPIC, ENABLED_TOPIC, Controller, parse_enabled
from node_demo.driver import Driver
from node_demo.publisher import Publisher
from node_demo.scenario import load_scenarios

# How long to wait for the broker to hand over the retained `enabled` flag on boot. A retained
# message arrives right after SUBSCRIBE, so this only bounds a dead or empty broker.
RETAINED_WAIT_S = 2.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="node-demo: simulated van published under renewvan/demo/, switched on and off "
        "by renewvan/demo/enabled/set"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    config = load_config()
    scenarios = load_scenarios(config.scenario_dir)

    publisher = Publisher(config.mqtt)
    controller = Controller(scenarios, publisher)
    driver = Driver(controller, publisher)
    controller.set_waker(driver.wake.set)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: driver.stop())

    retained: list[bool] = []
    retained_seen = threading.Event()

    def on_retained_state(payload: str) -> None:
        # Only the first delivery is the boot value; later ones are our own republishes.
        if retained_seen.is_set():
            return
        value = parse_enabled(payload)
        if value is not None:
            retained.append(value)
        retained_seen.set()

    publisher.subscribe(ENABLED_TOPIC, on_retained_state)
    publisher.connect()
    retained_seen.wait(RETAINED_WAIT_S)
    # Commands only after the boot state is applied, so an early `/set` cannot be overwritten.
    controller.start(retained_enabled=bool(retained and retained[0]))
    publisher.subscribe(ENABLED_SET_TOPIC, controller.on_command)

    driver.run()


if __name__ == "__main__":
    main()
