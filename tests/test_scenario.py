import json
from pathlib import Path

import pytest

from node_demo.scenario import (
    Scenario,
    Step,
    initial_messages,
    load_scenarios,
    messages_at,
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


def test_topics_use_demo_root_never_real_root(scenarios):
    for s in scenarios:
        for tick in range(s.loop_s):
            for topic in messages_at(s, tick):
                assert topic.startswith(f"renewvan-demo/{s.entity}/{s.id}/")
                assert not topic.startswith("renewvan/")
                assert len(topic.split("/")) == 4


def test_values_round_trip_through_json(scenarios):
    for s in scenarios:
        for tick in range(s.loop_s):
            for value in messages_at(s, tick).values():
                assert json.loads(json.dumps(value)) == value


def test_t0_step_overlays_initial_on_reset():
    s = Scenario("tank", "x", "d", 10, {"a": 1, "b": 2}, (Step(0, {"a": 9}), Step(5, {"b": 3})))
    assert messages_at(s, 0) == {"renewvan-demo/tank/x/a": 9, "renewvan-demo/tank/x/b": 2}
    assert messages_at(s, 5) == {"renewvan-demo/tank/x/b": 3}
    assert messages_at(s, 10) == messages_at(s, 0)
