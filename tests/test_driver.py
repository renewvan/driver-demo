import threading

from driver_demo.driver import Driver


class FakeController:
    def __init__(self, fail_on=None):
        self.events: list[tuple[str, int | None]] = []
        self.fail_on = fail_on

    def tick(self, n):
        self.events.append(("tick", n))
        if n == self.fail_on:
            raise RuntimeError("boom")

    def apply_pending(self, now_tick):
        self.events.append(("apply", now_tick))
        return True

    def shutdown(self):
        self.events.append(("shutdown", None))


class FakePublisher:
    def __init__(self, events):
        self.events = events

    def mark_offline(self):
        self.events.append(("offline", None))

    def flush(self, timeout=5.0):
        self.events.append(("flush", None))
        return True

    def disconnect(self):
        self.events.append(("disconnect", None))


class FakeWake(threading.Event):
    """A scripted sleep: each wait() advances a fake clock by what the script says, and can
    deliver a wake (a queued command) or a stop part-way through."""

    def __init__(self, stop: threading.Event, script):
        super().__init__()
        self.stop = stop
        self.script = list(script)
        self.now = 1000.0
        self.waits: list[float] = []

    def clock(self):
        return self.now

    def wait(self, timeout=None):
        self.waits.append(timeout)
        kind, advance = self.script.pop(0) if self.script else ("stop", 0)
        # A real sleep consumes exactly the time it was asked for; a wake cuts it short.
        self.now += timeout if kind == "tick" else advance
        if kind == "wake":
            self.set()
        elif kind == "stop":
            self.stop.set()
            self.set()
        return self.is_set()


def make(script, controller=None):
    controller = controller or FakeController()
    publisher = FakePublisher(controller.events)
    stop = threading.Event()
    wake = FakeWake(stop, script)
    driver = Driver(controller, publisher, stop, clock=wake.clock, wake=wake)
    return driver, controller, wake


def ticks(controller):
    return [n for k, n in controller.events if k == "tick"]


def test_ticks_are_numbered_from_one_and_run_until_stopped():
    # waiting out the full second delivers no wake; the script's own "tick" kind just advances time
    driver, controller, _ = make([("tick", 1.0)] * 3 + [("stop", 0)])
    driver.run()
    assert ticks(controller) == [1, 2, 3]


def test_shutdown_clears_the_van_before_going_offline_and_disconnecting():
    driver, controller, _ = make([("tick", 1.0)] * 2)
    driver.run()
    kinds = [k for k, _ in controller.events]
    assert kinds[kinds.index("shutdown") :] == ["shutdown", "offline", "flush", "disconnect"]


def test_shutdown_still_runs_if_a_tick_raises():
    driver, controller, _ = make([("tick", 1.0)] * 5, FakeController(fail_on=2))
    try:
        driver.run()
    except RuntimeError:
        pass
    assert ("shutdown", None) in controller.events
    assert ("disconnect", None) in controller.events


def test_sleeps_to_absolute_deadlines_without_drift():
    driver, _, wake = make([("tick", 1.0)] * 5)
    driver.run()
    assert wake.waits[:5] == [1.0] * 5


def test_late_tick_does_not_sleep_and_catches_up():
    driver, controller, wake = make([("tick", 1.0)] * 4)
    real_tick = controller.tick

    def slow_tick(n):
        if n == 1:
            wake.now += 2.5  # tick 1 takes 2.5 s
        real_tick(n)

    controller.tick = slow_tick  # type: ignore[method-assign]
    driver.run()
    assert wake.waits[0] == 1.0
    assert wake.waits[1] == 0.0  # tick 2 (due +2.0) already overdue at +3.5
    assert wake.waits[2] == 0.0  # tick 3 (due +3.0) too
    assert wake.waits[3] == 0.5  # tick 4 due +4.0, back on the grid


def test_a_wake_applies_the_command_without_consuming_a_scenario_tick():
    """Toggling must not advance the scenario clock, or every toggle would speed the demo up."""
    driver, controller, wake = make([("wake", 0.4), ("tick", 0.6), ("tick", 1.0)])
    driver.run()
    assert [e for e in controller.events if e[0] in ("tick", "apply")] == [
        ("apply", 1),
        ("tick", 1),
        ("tick", 2),
    ]


def test_a_wake_resumes_waiting_for_the_same_deadline():
    driver, _, wake = make([("wake", 0.4), ("tick", 0.6)])
    driver.run()
    assert wake.waits[0] == 1.0
    assert abs(wake.waits[1] - 0.6) < 1e-9, "after a wake only the rest of the second remains"


def test_stop_interrupts_the_sleep_and_does_not_apply_a_command():
    driver, controller, _ = make([("stop", 0)])
    driver.run()
    assert not [e for e in controller.events if e[0] in ("apply", "tick")]
    assert ("shutdown", None) in controller.events
