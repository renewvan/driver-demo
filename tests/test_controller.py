from pathlib import Path

from node_demo.controller import ENABLED_SET_TOPIC, ENABLED_TOPIC, Controller, parse_enabled
from node_demo.scenario import initial_messages, load_scenarios

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"
SCENARIOS = load_scenarios(SCENARIO_DIR)
INITIAL = {t: v for s in SCENARIOS for t, v in initial_messages(s).items()}
ROUTER_HEALTH = "renewvan/demo/router/health"


def a_property_that_moves():
    """(topic, initial value, tick it first changes at): a property a timeline step overwrites."""
    for s in SCENARIOS:
        for step in s.timeline:
            for prop, value in step.set.items():
                topic = f"renewvan/demo/{s.entity}/{s.id}/{prop}"
                if value != INITIAL[topic]:
                    return topic, INITIAL[topic], step.t
    raise AssertionError("no scenario ever changes a property")


class FakePublisher:
    def __init__(self):
        self.json: dict[str, object] = {}
        self.raw: dict[str, str] = {}
        self.cleared: list[str] = []
        self.flushes = 0

    def publish(self, topic, payload):
        self.json[topic] = payload

    def publish_raw(self, topic, payload):
        self.raw[topic] = payload

    def clear(self, topic):
        self.cleared.append(topic)
        self.json.pop(topic, None)
        self.raw.pop(topic, None)

    def flush(self, timeout=5.0):
        self.flushes += 1
        return True


def make(enabled=False):
    pub = FakePublisher()
    c = Controller(SCENARIOS, pub)
    if enabled:
        c.set_enabled(True)
    return c, pub


def van(pub):
    """Everything published except the switch itself."""
    return {t: v for t, v in pub.json.items() if t != ENABLED_TOPIC}


def test_parse_enabled_accepts_only_json_booleans():
    assert parse_enabled("true") is True
    assert parse_enabled("false") is False
    for bad in ("", "1", "on", '"true"', "null", "TRUE", "yes"):
        assert parse_enabled(bad) is None


def test_starts_disabled_and_publishes_no_van():
    c, pub = make()
    c.start()
    assert pub.json[ENABLED_TOPIC] is False
    assert van(pub) == {}
    assert pub.raw == {}


def test_enabling_publishes_every_initial_record_and_router_health():
    c, pub = make()
    c.start()
    c.set_enabled(True)
    assert pub.json[ENABLED_TOPIC] is True
    assert van(pub) == INITIAL
    assert pub.raw[ROUTER_HEALTH] == "online"


def test_disabling_clears_the_van_but_keeps_the_enabled_flag():
    c, pub = make(enabled=True)
    c.set_enabled(False)
    assert pub.json == {ENABLED_TOPIC: False}
    assert pub.raw == {}
    assert set(pub.cleared) == set(INITIAL) | {ROUTER_HEALTH}


def test_enabling_twice_does_not_restart_the_loop():
    c, pub = make(enabled=True)
    topic, _, at = a_property_that_moves()
    c.tick(at)
    moved = pub.json[topic]
    c.set_enabled(True)
    assert pub.json[topic] == moved


def test_ticks_publish_nothing_while_disabled():
    c, pub = make()
    c.start()
    before = dict(pub.json)
    for n in range(1, 130):
        c.tick(n)
    assert pub.json == before


def test_re_enabling_restarts_from_the_initial_state():
    c, pub = make(enabled=True)
    topic, initial, at = a_property_that_moves()
    c.tick(at)
    assert pub.json[topic] != initial, "the scenario should have moved by now"
    c.set_enabled(False)
    c.set_enabled(True)
    assert pub.json[topic] == initial


def test_command_handler_ignores_garbage_and_applies_valid_payloads():
    c, pub = make()
    c.start()
    c.on_command("nonsense")
    c.tick(1)
    assert pub.json[ENABLED_TOPIC] is False
    c.on_command("true")
    c.tick(2)
    assert pub.json[ENABLED_TOPIC] is True
    c.on_command("false")
    c.tick(3)
    assert pub.json[ENABLED_TOPIC] is False


def test_restart_with_retained_enabled_true_resumes_from_the_initial_state():
    c, pub = make()
    c.start(retained_enabled=True)
    assert pub.json[ENABLED_TOPIC] is True
    assert van(pub) == INITIAL


def test_shutdown_clears_the_van_and_leaves_the_enabled_flag_for_the_next_boot():
    c, pub = make(enabled=True)
    c.shutdown()
    assert set(pub.cleared) == set(INITIAL) | {ROUTER_HEALTH}
    assert pub.json.get(ENABLED_TOPIC) is True
    assert ENABLED_SET_TOPIC not in pub.json


def test_command_handler_never_blocks_the_mqtt_thread():
    """on_command runs on paho's network thread, which also delivers PUBACKs: if it flushes (waits
    for acks) there, it deadlocks until the timeout and nothing is cleared."""
    c, pub = make(enabled=True)
    flushes_before = pub.flushes
    c.on_command("false")
    assert pub.flushes == flushes_before, "on_command must only enqueue, never flush"
    assert c.enabled, "the state change is applied by the driver thread, not the MQTT thread"
    c.tick(1)
    assert not c.enabled
    assert set(pub.cleared) == set(INITIAL) | {ROUTER_HEALTH}
    assert pub.json[ENABLED_TOPIC] is False


def test_latest_queued_command_wins():
    c, pub = make()
    c.start()
    c.on_command("true")
    c.on_command("false")
    c.on_command("true")
    c.tick(1)
    assert c.enabled
    assert van(pub) == INITIAL


def test_enabling_mid_run_starts_every_scenario_at_its_beginning():
    """The loop is relative to when the demo was switched on, not to the driver's tick count."""
    c, pub = make()
    c.start()
    topic, initial, at = a_property_that_moves()
    c.on_command("true")
    c.tick(500)
    assert pub.json[topic] == initial
    c.tick(500 + at)
    assert pub.json[topic] != initial


class CountingPublisher(FakePublisher):
    def __init__(self):
        super().__init__()
        self.counts: dict[str, int] = {}

    def publish(self, topic, payload):
        self.counts[topic] = self.counts.get(topic, 0) + 1
        super().publish(topic, payload)


def test_switching_on_publishes_every_initial_value_exactly_once():
    """The driver applies a queued command WITHOUT consuming a scenario tick, so its next regular
    tick has the same number. That tick must not replay tick 0 and publish the whole initial
    record a second time (it landed on the right values, so only the traffic doubled)."""
    pub = CountingPublisher()
    c = Controller(SCENARIOS, pub)
    c.start()
    c.on_command("true")
    c.apply_pending(7)  # the wake path: applied at tick 7, tick 7 not yet consumed
    c.tick(7)  # the regular tick with the same number
    c.tick(8)
    twice = {t: n for t, n in pub.counts.items() if n > 1 and t != ENABLED_TOPIC}
    assert not twice, f"republished: {sorted(twice)[:3]}"


def test_a_scenario_still_loops_after_a_wake_applied_enable():
    pub = CountingPublisher()
    c = Controller(SCENARIOS, pub)
    c.start()
    c.on_command("true")
    c.apply_pending(100)
    topic, initial, at = a_property_that_moves()
    c.tick(100 + at)
    assert pub.json[topic] != initial
    loop = max(s.loop_s for s in SCENARIOS)
    c.tick(100 + loop)  # one full loop later: back to the initial record
    assert pub.json[topic] == initial


def test_the_enabled_flag_is_published_only_when_it_changes():
    """A client re-renders on every `enabled` message; repeating an unchanged state is noise."""
    pub = CountingPublisher()
    c = Controller(SCENARIOS, pub)
    c.start()
    assert pub.counts[ENABLED_TOPIC] == 1  # boot publishes the state once
    c.on_command("true")
    c.tick(1)
    assert pub.counts[ENABLED_TOPIC] == 2
    c.on_command("true")  # already on
    c.tick(2)
    c.on_command("true")
    c.tick(3)
    assert pub.counts[ENABLED_TOPIC] == 2, "a repeated command must not republish the state"
    c.on_command("false")
    c.tick(4)
    assert pub.counts[ENABLED_TOPIC] == 3
