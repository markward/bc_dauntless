"""Symlink support, which is not a given on Windows.

Creating a symlink there needs SeCreateSymbolicLinkPrivilege: Developer Mode
on, or an elevated process. Without it os.symlink raises
OSError(WinError 1314), and a test whose SUBJECT is "we do not follow links"
dies in its own setup with an error that says nothing about the behaviour
under test.

Skipping is the honest outcome. The behaviour these tests cover is about how
WE treat a link once one exists; whether this machine may create one is a
property of the machine, not of the code.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def _probe() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "target"
        target.mkdir()
        try:
            (Path(tmp) / "link").symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError, AttributeError):
            return False
        return True


# Probed once: the answer cannot change inside a run, and the probe touches
# the filesystem.
CAN_SYMLINK = _probe()

requires_symlinks = pytest.mark.skipif(
    not CAN_SYMLINK,
    reason="creating a symlink needs Developer Mode or elevation on Windows "
           "(SeCreateSymbolicLinkPrivilege); see tests/helpers/symlinks.py")
