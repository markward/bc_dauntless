"""Tests for host-loop lighting wiring (Phase-1 lights → renderer)."""
import os

import pytest


def test_set_lighting_binding_smoke():
    """Calling set_lighting on the bindings module does not raise."""
    import _open_stbc_host
    _open_stbc_host.set_lighting(
        (0.2, 0.3, 0.4),
        [
            ((0.0, -1.0, 0.0), (1.0, 0.9, 0.8)),
            ((1.0, 0.0, 0.0), (0.5, 0.5, 0.5)),
        ],
    )


def test_set_lighting_accepts_empty_directionals():
    import _open_stbc_host
    _open_stbc_host.set_lighting((0.5, 0.5, 0.5), [])


def test_set_lighting_clamps_to_max_directionals():
    """Passing more than 4 directionals must not raise (truncation in C++)."""
    import _open_stbc_host
    _open_stbc_host.set_lighting(
        (0.1, 0.1, 0.1),
        [((0.0, 1.0, 0.0), (1.0, 1.0, 1.0))] * 8,
    )
