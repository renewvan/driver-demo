"""The demo namespace sits INSIDE the real root (`renewvan/demo/...`), so every consumer of
`renewvan/#` receives it. These tests pin the properties that keep that safe, from the point of
view of the consumers that matter, rather than the exact strings.
"""

from pathlib import Path

from node_demo.controller import ENABLED_SET_TOPIC, ENABLED_TOPIC, ROUTER_HEALTH_TOPIC
from node_demo.publisher import HEALTH_TOPIC
from node_demo.scenario import TOPIC_ROOT, initial_messages, load_scenarios

SCENARIOS = load_scenarios(Path(__file__).resolve().parent.parent / "scenarios")
# Entity domains the real bus and its consumers know (hub schema/*.schema.json, dashboard, logger).
ENTITY_DOMAINS = {
    "tank",
    "relay",
    "battery",
    "solar",
    "charger",
    "router",
    "gps",
    "temperature",
    "tilt",
}
NON_ENTITY_TOPICS = [ENABLED_TOPIC, ENABLED_SET_TOPIC, ROUTER_HEALTH_TOPIC, HEALTH_TOPIC]


def every_topic():
    for s in SCENARIOS:
        yield from initial_messages(s)
    yield from NON_ENTITY_TOPICS


def test_everything_lives_under_renewvan_demo():
    assert TOPIC_ROOT == "renewvan/demo"
    assert all(t.startswith("renewvan/demo/") for t in every_topic())


def test_the_demo_segment_is_never_an_entity_domain():
    """`renewvan/<domain>/<id>/<property>` is how every consumer recognises an entity. `demo` in
    the domain slot must never be one, or a consumer could read a demo topic as a real entity."""
    assert "demo" not in ENTITY_DOMAINS


def test_no_demo_topic_is_a_four_segment_real_entity_topic():
    """The logger writes `renewvan/<domain>/<id>/<property>` (exactly four segments) for entity
    domains. Demo entity topics have five, and every other demo topic has a non-entity domain."""
    for topic in every_topic():
        parts = topic.split("/")
        looks_real = len(parts) == 4 and parts[1] in ENTITY_DOMAINS
        assert not looks_real, topic


def test_scenario_ids_do_not_shadow_a_real_domain_or_the_driver_liveness_id():
    """`renewvan/<domain>/driver/status` is a liveness topic consumers drop by id."""
    for s in SCENARIOS:
        assert s.id != "driver"
        assert "/" not in s.id and "#" not in s.id and "+" not in s.id
