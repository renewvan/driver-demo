"""scenarios/ is a committed copy of hub/schema/demo/ (the source of truth), so the image
builds self-contained. Catch drift locally when the hub repo sits alongside this one."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HUB_DEMO = ROOT.parent / "hub" / "schema" / "demo"


@pytest.mark.skipif(not HUB_DEMO.is_dir(), reason="../hub/schema/demo not present")
def test_scenarios_match_hub_byte_for_byte():
    hub = {p.name: p.read_bytes() for p in HUB_DEMO.glob("*.demo.json")}
    local = {p.name: p.read_bytes() for p in (ROOT / "scenarios").glob("*.demo.json")}
    assert local.keys() == hub.keys(), "run scripts/sync-scenarios.sh"
    assert [n for n in hub if hub[n] != local[n]] == [], "run scripts/sync-scenarios.sh"
