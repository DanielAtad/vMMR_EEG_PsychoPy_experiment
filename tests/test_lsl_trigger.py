import importlib
import sys
import threading
import time
import types

import pytest


class FakeStreamInfo:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeStreamOutlet:
    instances = []

    def __init__(self, info):
        self.info = info
        self.samples = []
        self._samples_lock = threading.Lock()
        self.consumer_connected = True
        self.__class__.instances.append(self)

    def push_sample(self, sample, timestamp=None, pushthrough=False):
        with self._samples_lock:
            self.samples.append({
                "value": int(sample[0]),
                "timestamp": timestamp,
                "pushthrough": pushthrough,
                "wall_time": time.monotonic(),
            })

    def wait_for_consumers(self, timeout):
        return self.consumer_connected

    def snapshot(self):
        with self._samples_lock:
            return list(self.samples)


@pytest.fixture
def lsl_module(monkeypatch):
    FakeStreamOutlet.instances.clear()
    fake_pylsl = types.ModuleType("pylsl")
    fake_pylsl.StreamInfo = FakeStreamInfo
    fake_pylsl.StreamOutlet = FakeStreamOutlet
    fake_pylsl.local_clock = time.monotonic
    monkeypatch.setitem(sys.modules, "pylsl", fake_pylsl)
    sys.modules.pop("lsl_trigger", None)
    module = importlib.import_module("lsl_trigger")
    yield module
    sys.modules.pop("lsl_trigger", None)


def wait_until(predicate, timeout=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def test_lsl_event_sample_uses_the_returned_explicit_timestamp(lsl_module):
    trigger = lsl_module.LSLTrigger(
        enabled=True, keepalive_hz=200, nominal_srate=1200,
        hold_duration=0.040,
    )
    try:
        returned_timestamp = trigger.set_with_timestamp(42)
        explicit_events = [
            sample for sample in trigger.outlet.snapshot()
            if sample["value"] == 42 and sample["timestamp"] is not None
        ]
        assert len(explicit_events) == 1
        assert explicit_events[0]["timestamp"] == returned_timestamp
        assert explicit_events[0]["pushthrough"] is True
        assert trigger.outlet.info.kwargs["channel_format"] == "int32"
    finally:
        trigger.stop()


def test_lsl_latch_auto_expires_and_repeated_code_gets_new_edge(lsl_module):
    hold_duration = 0.040
    trigger = lsl_module.LSLTrigger(
        enabled=True, keepalive_hz=400, nominal_srate=1200,
        hold_duration=hold_duration,
    )
    assert trigger.requires_manual_clear is False
    try:
        first_timestamp = trigger.set_with_timestamp(17)
        samples = trigger.outlet.snapshot()
        first_event_index = next(
            index for index, sample in enumerate(samples)
            if sample["value"] == 17 and sample["timestamp"] is not None
        )

        time.sleep(hold_duration / 2)
        after_first_event = trigger.outlet.snapshot()[first_event_index + 1:]
        assert all(sample["value"] == 17 for sample in after_first_event)

        assert wait_until(
            lambda: any(
                sample["value"] == 0
                for sample in trigger.outlet.snapshot()[first_event_index + 1:]
            )
        )
        second_timestamp = trigger.set_with_timestamp(17)
        assert second_timestamp > first_timestamp

        values = [sample["value"] for sample in trigger.outlet.snapshot()]
        assert values[first_event_index] == 17
        assert 0 in values[first_event_index + 1:]
        last_zero = max(index for index, value in enumerate(values) if value == 0)
        assert 17 in values[last_zero + 1:]
    finally:
        trigger.stop()


def test_finish_holds_final_marker_then_clears_and_is_idempotent(lsl_module):
    hold_duration = 0.040
    margin = 0.015
    trigger = lsl_module.LSLTrigger(
        enabled=True, keepalive_hz=400, nominal_srate=1200,
        hold_duration=hold_duration,
    )

    start = time.monotonic()
    trigger.finish(final_code=99, margin=margin)
    elapsed = time.monotonic() - start

    samples = trigger.outlet.snapshot()
    final_index = next(
        index for index, sample in enumerate(samples)
        if sample["value"] == 99 and sample["timestamp"] is not None
    )
    first_zero_after = next(
        sample for sample in samples[final_index + 1:]
        if sample["value"] == 0
    )
    final_sample = samples[final_index]

    assert first_zero_after["wall_time"] - final_sample["wall_time"] >= 0.035
    assert elapsed >= hold_duration + margin - 0.010
    assert samples[-1]["value"] == 0
    assert trigger._keepalive_thread is None

    trigger.finish(final_code=99, margin=margin)
    trigger.stop()
    trigger.stop()
