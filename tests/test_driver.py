import threading
from pathlib import Path

from node_demo.driver import Driver
from node_demo.scenario import load_scenarios, messages_at

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"


class FakePublisher:
    def __init__(self):
        self.events: list[tuple[str, str | None]] = []
        self.raw_payloads: dict[str, str] = {}

    def publish(self, topic, payload):
        self.events.append(("publish", topic))

    def publish_raw(self, topic, payload):
        self.events.append(("publish_raw", topic))
        self.raw_payloads[topic] = payload

    def clear(self, topic):
        self.events.append(("clear", topic))

    def flush(self, timeout=5.0):
        self.events.append(("flush", None))
        return True

    def mark_offline(self):
        self.events.append(("offline", None))

    def disconnect(self):
        self.events.append(("disconnect", None))

    def topics(self, kind):
        return [t for k, t in self.events if k == kind]


class FakeClock:
    """Each stop.wait(timeout) advances time by exactly `timeout`; stops after `ticks` waits."""

    def __init__(self, stop: threading.Event, ticks: int):
        self.now = 1000.0
        self.stop = stop
        self.ticks = ticks
        self.waits: list[float] = []

    def __call__(self):
        return self.now

    def wait(self, timeout):
        self.waits.append(timeout)
        self.now += timeout
        if len(self.waits) > self.ticks:
            self.stop.set()
        return self.stop.is_set()


def make_driver(ticks, publisher=None):
    scenarios = load_scenarios(SCENARIO_DIR)
    publisher = publisher or FakePublisher()
    stop = threading.Event()
    clock = FakeClock(stop, ticks)
    stop.wait = clock.wait  # type: ignore[method-assign]
    return Driver(scenarios, publisher, stop, clock=clock), publisher, clock, scenarios


def test_startup_publishes_every_scenarios_initial_state():
    driver, pub, _, scenarios = make_driver(0)
    driver.run()
    expected = {t for s in scenarios for t in messages_at(s, 0)}
    assert set(pub.topics("publish")) == expected


def test_shutdown_clears_every_published_topic_before_health_offline():
    driver, pub, _, scenarios = make_driver(125)  # crosses the 120 s loop restart
    driver.run()
    published = set(pub.topics("publish")) | set(pub.topics("publish_raw"))
    assert published
    assert sorted(pub.topics("clear")) == sorted(published)
    kinds = [k for k, _ in pub.events]
    last_clear = max(i for i, k in enumerate(kinds) if k == "clear")
    assert kinds.index("offline") > last_clear
    assert "flush" in kinds[last_clear : kinds.index("offline")]  # clears acked before offline
    assert kinds.index("disconnect") > kinds.index("offline")
    assert not any(k == "publish" for k in kinds[last_clear:])


def test_shutdown_clears_topics_even_if_loop_raises():
    driver, pub, _, _ = make_driver(0)
    driver.tick(0)

    def boom(*_):
        raise RuntimeError("boom")

    driver._stop.wait = boom  # type: ignore[method-assign]
    try:
        driver.run()
    except RuntimeError:
        pass
    assert pub.topics("clear")
    assert ("offline", None) in pub.events


def test_sleeps_to_absolute_deadlines_without_drift():
    driver, _, clock, _ = make_driver(5)
    driver.run()
    # clock only advances inside wait, so each wait must be exactly 1 s to the next boundary
    assert clock.waits[:5] == [1.0] * 5


def test_late_tick_does_not_sleep_and_catches_up():
    driver, pub, clock, _ = make_driver(3)
    real_tick = driver.tick

    def slow_tick(n):
        if n == 1:
            clock.now += 2.5  # tick 1 takes 2.5 s
        real_tick(n)

    driver.tick = slow_tick  # type: ignore[method-assign]
    driver.run()
    assert clock.waits[0] == 1.0
    assert clock.waits[1] == 0.0  # tick 2 (due +2.0) already overdue at +3.5
    assert clock.waits[2] == 0.0  # tick 3 (due +3.0) too
    assert clock.waits[3] == 0.5  # tick 4 due +4.0, back on the grid


def test_router_scenario_announces_router_health_raw_and_clears_it_on_shutdown():
    driver, pub, _, _ = make_driver(0)
    driver.run()
    assert pub.topics("publish_raw") == ["renewvan-demo/router/health"]
    # Raw, not JSON: the dashboard compares the literal string `online`.
    assert pub.raw_payloads == {"renewvan-demo/router/health": "online"}
    assert "renewvan-demo/router/health" in pub.topics("clear")


def test_no_router_scenario_means_no_router_health():
    scenarios = [s for s in load_scenarios(SCENARIO_DIR) if s.entity != "router"]
    pub = FakePublisher()
    stop = threading.Event()
    clock = FakeClock(stop, 0)
    stop.wait = clock.wait  # type: ignore[method-assign]
    Driver(scenarios, pub, stop, clock=clock).run()
    assert not [e for e in pub.events if e[0] == "publish_raw"]
