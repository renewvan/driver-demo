# node-demo

A simulated van on the renewvan bus, so the dashboard (and any other consumer) can be
developed and shown without a van, a Pi, or hardware. It replays the scenarios in
[`scenarios/`](scenarios/) on a shared 1 Hz clock under a **separate topic root**,
`renewvan-demo/`, so demo values never overwrite retained real state on `renewvan/` and never
reach the logger / InfluxDB.

Inspired by Venus OS's Demo mode: `dbus-recorder`'s `play.py` replays recordings of real
services under the same D-Bus service names the real hardware uses, loops them, and resets to
the recording's initial state at the end of each loop. `node-demo` does the same on MQTT: the
same entities and property names as the real bus, a looping timeline per entity, and a full
reset to the initial record at each loop restart.

## Topic contract

Authoritative: [`hub/docs/demo-mode.md`](../hub/docs/demo-mode.md).

| Topic | Payload |
|---|---|
| `renewvan-demo/<entity>/<id>/<property>` | `json.dumps(value)`, retained, QoS 1 (identical encoding to `renewvan/...`) |
| `renewvan-demo/health` | `online` / `offline` (LWT), retained |

- At loop start (and on process start) every property of every scenario's `initial` record is
  published; at `t` seconds into the loop only the properties of the timeline step at `t`.
- On `SIGTERM`/`SIGINT` it clears every retained topic it published (empty retained payload,
  the ADR 0008 "no value" convention), waits for the broker to acknowledge, then publishes
  `renewvan-demo/health` = `offline` and exits. Nothing but the health topic lingers.
- Command topics (`.../set`) are not simulated; demo state is read-only.

## Scenarios

Owned by the hub repo (`hub/schema/demo/`, the source of truth, validated by
`hub/schema/validate-demo.py`). `scenarios/` here is a committed copy so CI and `docker build`
are self-contained. Refresh it after changing the hub scenarios:

```bash
scripts/sync-scenarios.sh        # copies ../hub/schema/demo/*.demo.json into scenarios/
```

`tests/test_scenarios_in_sync.py` fails when `../hub` is present and the copy has drifted.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `MQTT_HOST` | `mosquitto` | Renewvan bus broker |
| `MQTT_PORT` | `1883` | |
| `MQTT_USERNAME` | _(none)_ | |
| `MQTT_PASSWORD` | _(none)_ | |
| `DEMO_SCENARIO_DIR` | `/app/scenarios` | directory of `*.demo.json` (baked into the image) |

## Running

```bash
pip install -r requirements.txt
MQTT_HOST=localhost DEMO_SCENARIO_DIR=./scenarios python -m node_demo.main
```

```bash
docker build -t node-demo .
docker run --rm --network host -e MQTT_HOST=localhost node-demo
```

Watch it: `mosquitto_sub -t 'renewvan-demo/#' -v`.

## Testing

```bash
pip install -r requirements.txt -r requirements-test.txt
pytest tests/ -v
```

No broker needed: `node_demo/scenario.py` is pure and the driver is tested with a fake publisher.

## Releasing

Tagging a GitHub release builds and publishes `ghcr.io/<owner>/node-demo:<tag>`, which `hub`'s
deployment compose file pins by tag (never builds from source).
