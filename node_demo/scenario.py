"""Demo scenarios: pure functions from (scenario, tick) to the topics to publish.

A scenario file (`<entity>[.<name>].demo.json`, envelope `hub/schema/demo.schema.json`)
holds one complete `initial` record and timeline steps that overlay `set` at `t` seconds
into a loop of `loop_s` seconds. See hub/docs/demo-mode.md.

The simulated Node fleet is a separate hub-owned file (`*.demo-fleet.json`, envelope
`hub/schema/demo-fleet.schema.json`) with its own loader: the entity glob never matches it.

No I/O except `load_scenarios` and `load_fleet`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The simulated van's namespace, one level inside the real `renewvan/` root. `demo` is not an
# entity domain, so no consumer reads it as a real entity, and the logger (exactly four segments,
# entity domains only) drops all of it. It is the single place the root is spelled.
TOPIC_ROOT = "renewvan/demo"


@dataclass(frozen=True)
class Step:
    t: int
    set: dict[str, Any]


@dataclass(frozen=True)
class Scenario:
    entity: str
    id: str
    description: str
    loop_s: int
    initial: dict[str, Any]
    timeline: tuple[Step, ...]

    def topic(self, prop: str) -> str:
        return f"{TOPIC_ROOT}/{self.entity}/{self.id}/{prop}"


def scenario_from_dict(doc: dict[str, Any]) -> Scenario:
    return Scenario(
        entity=doc["entity"],
        id=doc["id"],
        description=doc["description"],
        loop_s=doc["loop_s"],
        initial=dict(doc["initial"]),
        timeline=tuple(Step(t=s["t"], set=dict(s["set"])) for s in doc["timeline"]),
    )


def load_scenarios(directory: Path | str) -> list[Scenario]:
    """Read every `*.demo.json` in `directory`, sorted by file name."""
    paths = sorted(Path(directory).glob("*.demo.json"))
    if not paths:
        raise FileNotFoundError(f"no *.demo.json scenarios in {directory}")
    return [scenario_from_dict(json.loads(p.read_text())) for p in paths]


@dataclass(frozen=True)
class HealthStep:
    t: int
    health: str


@dataclass(frozen=True)
class FleetNode:
    node: str
    health: str
    info: dict[str, Any] | None
    health_timeline: tuple[HealthStep, ...]

    def topic(self, leaf: str) -> str:
        return f"{TOPIC_ROOT}/{self.node}/{leaf}"


@dataclass(frozen=True)
class Fleet:
    description: str
    loop_s: int
    nodes: tuple[FleetNode, ...]


@dataclass(frozen=True)
class FleetMessages:
    """What to publish at one tick. `info` is JSON-encoded on the wire, `health` a bare word."""

    info: dict[str, Any]
    health: dict[str, str]


def fleet_from_dict(doc: dict[str, Any]) -> Fleet:
    return Fleet(
        description=doc["description"],
        loop_s=doc["loop_s"],
        nodes=tuple(
            FleetNode(
                node=n["node"],
                health=n["health"],
                info=dict(n["info"]) if "info" in n else None,
                health_timeline=tuple(
                    HealthStep(t=s["t"], health=s["health"]) for s in n.get("health_timeline", ())
                ),
            )
            for n in doc["nodes"]
        ),
    )


def load_fleet(directory: Path | str) -> Fleet:
    """Read the one `*.demo-fleet.json` in `directory`."""
    paths = sorted(Path(directory).glob("*.demo-fleet.json"))
    if len(paths) != 1:
        raise FileNotFoundError(
            f"expected one *.demo-fleet.json in {directory}, found {len(paths)}"
        )
    return fleet_from_dict(json.loads(paths[0].read_text()))


def fleet_messages_at(fleet: Fleet, tick: int) -> FleetMessages:
    """Topics to publish at integer second `tick` (wrapped by `loop_s`).

    At loop start every Node's `health` (and `info`, when it has one); a `t == 0` health step
    overlays it. Otherwise only the health of the steps whose `t` equals the loop phase.
    """
    phase = tick % fleet.loop_s
    info: dict[str, Any] = {}
    health: dict[str, str] = {}
    for node in fleet.nodes:
        if phase == 0:
            health[node.topic("health")] = node.health
            if node.info is not None:
                info[node.topic("info")] = node.info
        for step in node.health_timeline:
            if step.t == phase:
                health[node.topic("health")] = step.health
    return FleetMessages(info=info, health=health)


def initial_messages(scenario: Scenario) -> dict[str, Any]:
    """Every property of the initial record, keyed by topic."""
    return {scenario.topic(prop): value for prop, value in scenario.initial.items()}


def messages_at(scenario: Scenario, tick: int) -> dict[str, Any]:
    """Topics to publish at integer second `tick` (wrapped by `loop_s`).

    At the start of each loop (`tick % loop_s == 0`) the full initial record, so a reset
    restores properties a previous loop's steps changed; any `t == 0` steps overlay it.
    Otherwise only the properties of the steps whose `t` equals the loop phase.
    """
    phase = tick % scenario.loop_s
    messages = initial_messages(scenario) if phase == 0 else {}
    for step in scenario.timeline:
        if step.t == phase:
            for prop, value in step.set.items():
                messages[scenario.topic(prop)] = value
    return messages
