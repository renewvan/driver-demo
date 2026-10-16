#!/usr/bin/env python3
"""node-demo entrypoint."""

from __future__ import annotations

import argparse
import logging
import signal
import threading

from node_demo.config import load_config
from node_demo.driver import Driver
from node_demo.publisher import Publisher
from node_demo.scenario import load_scenarios


def main() -> None:
    parser = argparse.ArgumentParser(
        description="node-demo: simulated van published under renewvan-demo/"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    config = load_config()
    scenarios = load_scenarios(config.scenario_dir)

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    publisher = Publisher(config.mqtt)
    publisher.connect()
    Driver(scenarios, publisher, stop).run()


if __name__ == "__main__":
    main()
