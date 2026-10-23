import json
from pathlib import Path

import pytest

from driver_demo.scenario import (
    Scenario,
    Step,
    fleet_from_dict,
    fleet_messages_at,
    initial_messages,
    load_fleet,
    load_scenarios,
    messages_at,
    scenario_from_dict,
)

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "scenarios"


@pytest.fixture(scope="module")
def scenarios() -> list[Scenario]:
    return load_scenarios(SCENARIO_DIR)


def by_name(scenarios, entity, id_):
    return next(s for s in scenarios if s.entity == entity and s.id == id_)


def test_loads_every_scenario_file(scenarios):
    assert len(scenarios) == len(list(SCENARIO_DIR.glob("*.demo.json"))) > 0


def test_load_scenarios_empty_dir_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_scenarios(tmp_path)


def test_initial_publishes_every_property(scenarios):
    for s in scenarios:
        msgs = initial_messages(s)
        assert msgs == {s.topic(p): v for p, v in s.initial.items()}
        assert len(msgs) == len(s.initial)


def test_tick_zero_is_the_full_initial_record(scenarios):
    for s in scenarios:
        expected = initial_messages(s)
        for step in s.timeline:
            if step.t == 0:
                expected.update({s.topic(p): v for p, v in step.set.items()})
        assert messages_at(s, 0) == expected


def test_step_publishes_only_its_set(scenarios):
    s = by_name(scenarios, "tank", "grey")
    step = next(st for st in s.timeline if st.t > 0)
    assert messages_at(s, step.t) == {s.topic(p): v for p, v in step.set.items()}
    assert len(messages_at(s, step.t)) < len(s.initial)


def test_idle_tick_publishes_nothing(scenarios):
    for s in scenarios:
        times = {st.t for st in s.timeline} | {0}
        idle = next(t for t in range(s.loop_s) if t not in times)
        assert messages_at(s, idle) == {}


def test_tick_wraps_at_loop_s_and_republishes_initial(scenarios):
    for s in scenarios:
        assert messages_at(s, s.loop_s) == messages_at(s, 0)
        assert messages_at(s, 5 * s.loop_s) == messages_at(s, 0)
        for step in s.timeline:
            assert messages_at(s, 3 * s.loop_s + step.t) == messages_at(s, step.t)


def test_property_changed_by_step_is_restored_at_loop_restart(scenarios):
    s = by_name(scenarios, "tank", "grey")
    changed = next(iter(s.timeline[-1].set))
    topic = s.topic(changed)
    assert messages_at(s, s.timeline[-1].t)[topic] != s.initial[changed]
    assert messages_at(s, s.loop_s)[topic] == s.initial[changed]


def test_every_changed_property_is_restored_at_reset(scenarios):
    for s in scenarios:
        reset = messages_at(s, s.loop_s)
        for step in s.timeline:
            for prop in step.set:
                if prop in s.initial:
                    assert reset[s.topic(prop)] == s.initial[prop]


def test_topics_are_the_scenarios_entity_under_the_demo_namespace(scenarios):
    """`renewvan/demo/<entity>/<id>/<property>` has five segments, so it can never be the
    four-segment `renewvan/<domain>/<id>/<property>` shape real consumers (the logger) act on."""
    for s in scenarios:
        for tick in range(s.loop_s):
            for topic in messages_at(s, tick):
                assert topic.startswith(f"renewvan/demo/{s.entity}/{s.id}/")
                assert len(topic.split("/")) == 5


def test_values_round_trip_through_json(scenarios):
    for s in scenarios:
        for tick in range(s.loop_s):
            for value in messages_at(s, tick).values():
                assert json.loads(json.dumps(value)) == value


def test_t0_step_overlays_initial_on_reset():
    s = Scenario("tank", "x", "d", 10, {"a": 1, "b": 2}, (Step(0, {"a": 9}), Step(5, {"b": 3})))
    assert messages_at(s, 0) == {"renewvan/demo/tank/x/a": 9, "renewvan/demo/tank/x/b": 2}
    assert messages_at(s, 5) == {"renewvan/demo/tank/x/b": 3}
    assert messages_at(s, 10) == messages_at(s, 0)


def test_the_entity_loader_does_not_load_the_fleet_file(scenarios):
    """Loading the fleet file as an entity scenario fails (it has no `entity`), so the entity
    loader must never see it: driver-demo would not start."""
    fleet_file = SCENARIO_DIR / "fleet.demo-fleet.json"
    assert fleet_file.is_file()
    with pytest.raises(KeyError):
        scenario_from_dict(json.loads(fleet_file.read_text()))
    assert fleet_file not in set(SCENARIO_DIR.glob("*.demo.json"))
    assert len(scenarios) == len(list(SCENARIO_DIR.glob("*.demo.json")))


def test_load_fleet_reads_the_fleet_file():
    fleet = load_fleet(SCENARIO_DIR)
    assert fleet.loop_s > 0
    assert any(n.driver == "router" for n in fleet.drivers)
    assert any(n.info is None for n in fleet.drivers), "a Driver with no info is part of the fleet"
    assert sum(1 for n in fleet.drivers if n.health_timeline) == 1, "exactly one Driver flaps"


def test_load_fleet_missing_file_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_fleet(tmp_path)


def a_fleet(*drivers, loop_s=10):
    return fleet_from_dict({"description": "d", "loop_s": loop_s, "drivers": list(drivers)})


def test_fleet_start_publishes_info_as_json_and_health_as_a_bare_word():
    info = {"driver": "tank", "product": "Tank", "version": "dev"}
    fleet = a_fleet({"driver": "tank", "health": "online", "info": info})
    msgs = fleet_messages_at(fleet, 0)
    assert msgs.info == {"renewvan/demo/tank/info": info}
    assert msgs.health == {"renewvan/demo/tank/health": "online"}


def test_a_driver_declared_with_no_info_publishes_only_health():
    fleet = a_fleet({"driver": "gps", "health": "online"})
    msgs = fleet_messages_at(fleet, 0)
    assert msgs.info == {}
    assert msgs.health == {"renewvan/demo/gps/health": "online"}


def test_an_offline_driver_keeps_its_info():
    fleet = a_fleet({"driver": "tilt", "health": "offline", "info": {"driver": "tilt"}})
    msgs = fleet_messages_at(fleet, 0)
    assert msgs.health == {"renewvan/demo/tilt/health": "offline"}
    assert "renewvan/demo/tilt/info" in msgs.info


def test_info_is_published_only_at_loop_start():
    fleet = a_fleet({"driver": "tank", "health": "online", "info": {"driver": "tank"}})
    assert fleet_messages_at(fleet, 3).info == {}
    assert fleet_messages_at(fleet, 10).info == {"renewvan/demo/tank/info": {"driver": "tank"}}


def flapping(loop_s=10):
    return a_fleet(
        {"driver": "steady", "health": "online"},
        {
            "driver": "router",
            "health": "online",
            "health_timeline": [{"t": 4, "health": "offline"}, {"t": 7, "health": "online"}],
        },
        loop_s=loop_s,
    )


def test_the_flapping_drivers_health_follows_its_timeline():
    fleet = flapping()
    topic = "renewvan/demo/router/health"
    assert fleet_messages_at(fleet, 0).health[topic] == "online"
    assert topic not in fleet_messages_at(fleet, 3).health
    assert fleet_messages_at(fleet, 4).health == {topic: "offline"}
    assert topic not in fleet_messages_at(fleet, 5).health
    assert fleet_messages_at(fleet, 7).health == {topic: "online"}


def test_the_flapping_drivers_health_resets_each_loop():
    """Reset is the republish of `health` at loop start, so a loop that ends offline recovers."""
    fleet = a_fleet(
        {
            "driver": "router",
            "health": "online",
            "health_timeline": [{"t": 6, "health": "offline"}],
        }
    )
    topic = "renewvan/demo/router/health"
    assert fleet_messages_at(fleet, 6).health == {topic: "offline"}
    assert fleet_messages_at(fleet, 10).health == {topic: "online"}
    assert fleet_messages_at(fleet, 26).health == {topic: "offline"}


def test_a_t0_health_step_overlays_the_loop_start_health():
    fleet = a_fleet(
        {"driver": "r", "health": "online", "health_timeline": [{"t": 0, "health": "offline"}]}
    )
    assert fleet_messages_at(fleet, 10).health == {"renewvan/demo/r/health": "offline"}


def test_fleet_topics_are_never_an_entity_topic():
    """An entity topic is `renewvan/demo/<entity>/<id>/<property>` (five segments). A Driver's
    `info` and `health` have four, so no consumer can read one as an entity property."""
    msgs = fleet_messages_at(load_fleet(SCENARIO_DIR), 0)
    assert msgs.info and msgs.health
    for topic in (*msgs.info, *msgs.health):
        assert topic.startswith("renewvan/demo/") and len(topic.split("/")) == 4


def test_identity_fields_are_published_retained_like_any_other_initial_property():
    """`driver` and `name` in a scenario's `initial` ride the same generic path as every other
    property: `renewvan/demo/<entity>/<id>/driver|name`, JSON-encoded, at every loop start."""
    s = scenario_from_dict(
        {
            "entity": "battery",
            "id": "wattcycle",
            "description": "d",
            "loop_s": 10,
            "initial": {"driver": "wattcycle", "name": "WattCycle bank", "soc_pct": 80},
            "timeline": [{"t": 5, "set": {"soc_pct": 79}}],
        }
    )
    expected = {
        "renewvan/demo/battery/wattcycle/driver": "wattcycle",
        "renewvan/demo/battery/wattcycle/name": "WattCycle bank",
        "renewvan/demo/battery/wattcycle/soc_pct": 80,
    }
    assert messages_at(s, 0) == expected
    assert messages_at(s, 10) == expected
    assert messages_at(s, 5) == {"renewvan/demo/battery/wattcycle/soc_pct": 79}


def test_every_scenario_that_names_a_driver_names_one_in_the_fleet(scenarios):
    """A scenario `driver` is the owning Driver's key, so it must be a fleet entry (the dashboard
    joins on it). Scenarios without it are legacy and stay valid."""
    keys = {d.driver for d in load_fleet(SCENARIO_DIR).drivers}
    for s in scenarios:
        if "driver" in s.initial:
            assert s.initial["driver"] in keys, f"{s.entity}.{s.id}"


def test_the_demo_van_has_two_battery_sources(scenarios):
    batteries = [s for s in scenarios if s.entity == "battery"]
    assert len(batteries) >= 2
    assert len({s.id for s in batteries}) == len(batteries)
