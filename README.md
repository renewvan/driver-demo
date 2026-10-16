# node-demo

A simulated van on the renewvan bus, so the dashboard (and any other consumer) can be
developed and shown without a van, a Pi, or hardware. It replays the scenarios in
[`scenarios/`](scenarios/) on a shared 1 Hz clock under a **separate topic root**,
`renewvan/demo/`, so demo values never overwrite retained real state (`renewvan/<entity>/...`) and
never reach the logger / InfluxDB (it only writes four-segment `renewvan/<entity-domain>/<id>/<prop>`
topics; demo entity topics have five).

Inspired by Venus OS's Demo mode: `dbus-recorder`'s `play.py` replays recordings of real
services under the same D-Bus service names the real hardware uses, loops them, and resets to
the recording's initial state at the end of each loop. `node-demo` does the same on MQTT: the
same entities and property names as the real bus, a looping timeline per entity, and a full
reset to the initial record at each loop restart.

## Topic contract

Authoritative: [`hub/docs/demo-mode.md`](../hub/docs/demo-mode.md).

| Topic | Direction | Payload |
|---|---|---|
| `renewvan/demo/enabled/set` | client → node-demo | JSON `true` / `false`, not retained: the command |
| `renewvan/demo/enabled` | node-demo → bus | JSON `true` / `false`, retained: the shared state every client follows |
| `renewvan/demo/<entity>/<id>/<property>` | node-demo → bus | `json.dumps(value)`, retained, QoS 1 (identical encoding to `renewvan/...`), only while on |
| `renewvan/demo/health` | node-demo → bus | bare `online` / `offline` (LWT), retained |
| `renewvan/demo/router/health` | node-demo → bus | bare `online` while on and a router scenario exists |

node-demo always runs and is **idle until switched on**: one MQTT connection and a 1 Hz tick that
publishes nothing. Any client turns the demo on or off for everyone by publishing the command.

- **Enabled:** every property of every scenario's `initial` record is published, then at `t`
  seconds into the loop only the properties of the timeline step at `t`. Every scenario restarts
  at its beginning each time the demo is switched on; a repeated `true` does not restart it.
- **Disabled:** every simulated topic is cleared (empty retained payload, the ADR 0008 "no value"
  convention) and `enabled` is republished as `false`.
- **Boot:** a retained `enabled: true` resumes the demo from the initial state; no retained
  value means off.
- **`SIGTERM`/`SIGINT`:** the van is cleared and the broker's acknowledgements awaited, then
  `renewvan/demo/health` is set to `offline`. `enabled` is left as it was, so a Pi that reboots
  in demo mode comes back in demo mode.
- Anything but a JSON boolean on `enabled/set` is ignored and logged.
- Entity command topics (`.../set`) are not simulated; demo state is read-only.
- It uses a clean MQTT session: all state is in retained topics, and a persistent session would
  replay a `/set` queued while the node was down.

`/set` runs on paho's network thread, which also receives the broker's acknowledgements, so it
only queues the request and the 1 Hz driver thread applies it (waiting for acks on the network
thread deadlocks until the timeout and nothing is cleared).

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

Switch it on and watch it:

```bash
mosquitto_pub -t renewvan/demo/enabled/set -m true
mosquitto_sub -t 'renewvan/demo/#' -v
```

## Testing

```bash
pip install -r requirements.txt -r requirements-test.txt
pytest tests/ -v
```

No broker needed: `scenario.py` and `controller.py` are pure and the driver is tested with a fake
controller and clock. The unit tests cannot see broker behaviour though (a fake publisher hid a
deadlock on the MQTT thread), so after changing the controller or publisher, run it against a
real mosquitto: toggle `enabled/set` from a second client, then confirm with
`mosquitto_sub -t 'renewvan/demo/#' --retained-only` that the van is gone after `false`.

## Releasing

Tagging a GitHub release builds and publishes `ghcr.io/<owner>/node-demo:<tag>`, which `hub`'s
deployment compose file pins by tag (never builds from source).
