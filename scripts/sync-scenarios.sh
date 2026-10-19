#!/usr/bin/env bash
# Refresh scenarios/ from the hub repo, the source of truth (hub/schema/demo/).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="${HUB_DIR:-$here/../hub}/schema/demo"
[ -d "$src" ] || { echo "hub scenarios not found: $src" >&2; exit 1; }
rm -f "$here"/scenarios/*.demo.json "$here"/scenarios/*.demo-fleet.json
cp "$src"/*.demo.json "$src"/*.demo-fleet.json "$here/scenarios/"
echo "synced $(ls "$here"/scenarios/*.demo.json | wc -l | tr -d ' ') scenarios and $(ls "$here"/scenarios/*.demo-fleet.json | wc -l | tr -d ' ') fleet file from $src"
