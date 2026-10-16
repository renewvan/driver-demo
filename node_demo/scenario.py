"""Demo scenarios: pure functions from (scenario, tick) to the topics to publish.

A scenario file (`<entity>[.<name>].demo.json`, envelope `hub/schema/demo.schema.json`)
holds one complete `initial` record and timeline steps that overlay `set` at `t` seconds
into a loop of `loop_s` seconds. See hub/docs/demo-mode.md.

No I/O except `load_scenarios`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TOPIC_ROOT = "renewvan-demo"


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
