from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import time
import warnings

import pytest
from fastapi._compat import v2
from pydantic.fields import FieldInfo
from pydantic.warnings import UnsupportedFieldAttributeWarning


def test_parallel_field_construction_preserves_warning_policy_and_validation(monkeypatch):
    first_entered, second_attempted, first_done = Event(), Event(), Event()
    counter_lock = Lock()
    calls = 0
    original = v2.TypeAdapter

    def interleaved_adapter(*args, **kwargs):
        nonlocal calls
        with counter_lock:
            calls += 1
            index = calls
        if index == 1:
            first_entered.set()
            assert second_attempted.wait(5)
            time.sleep(0.08)
        else:
            assert first_done.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(v2, 'TypeAdapter', interleaved_adapter)

    def build(first):
        if not first:
            second_attempted.set()
        try:
            field = v2.ModelField(FieldInfo(annotation=int, alias='wire_value'), name='value')
            assert field.alias == 'wire_value'
            assert field.validate('7', {}) == (7, [])
        finally:
            if first:
                first_done.set()

    with warnings.catch_warnings():
        warnings.simplefilter('error', UnsupportedFieldAttributeWarning)
        before = list(warnings.filters)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(build, True)
            assert first_entered.wait(5)
            second = pool.submit(build, False)
            first.result()
            second.result()
        assert warnings.filters == before
        with pytest.raises(UnsupportedFieldAttributeWarning):
            warnings.warn('fixture unsupported field', UnsupportedFieldAttributeWarning)
