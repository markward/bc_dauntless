"""Compiled-code cache for the SDK loader.

Both SDK loader twins (tools/mission_harness.py, the production loader, and
tests/conftest.py) parse each script and run the Python 1.5 compat transforms
before compiling. That is pure in the file's bytes and in which sibling files
exist (the implicit-relative-import rewrite looks them up), so the code
object is reused while neither has changed. Every load still EXECUTES the
code into its own module dict: only the parse/transform/compile is shared.

The validity stamp is (mtime_ns, size, ctime_ns, inode) of the file and of
each sibling directory; a directory's stamp moves when an entry is added,
removed or renamed, which covers a sibling appearing. One entry per (loader
twin, path, module name) -- a changed file replaces its entry rather than
accumulating.

On Windows a file's stamp also carries a digest of its bytes, because
st_ctime there is the CREATION time rather than the inode-change time and so
cannot act as the tiebreak the rest of the stamp leans on. See _stamp.
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
from typing import Callable, Iterable

_cache: dict = {}


# st_ctime means different things by platform. On POSIX it is the INODE
# CHANGE time, which the kernel moves on every write and which no API can set
# backwards -- that is what makes it a sound tiebreak. On Windows it is the
# CREATION time, which does not move when a file is rewritten at all.
#
# So on Windows every component of the cheap stamp can survive a real edit:
# same size, mtime restored by os.utime (a backup copy, `cp -p`, a restore
# from a scratch file), ctime never moved, and the inode index unchanged
# because the file was written in place. The cache then serves STALE compiled
# code after a genuine edit, with no error -- it just looks like the edit did
# not take effect. Measured on Windows 11, not inferred.
_CTIME_IS_CREATION_TIME = sys.platform == "win32"

# Enough bytes to make a collision not worth reasoning about, while staying
# far cheaper than the parse + 1.5 transforms + compile this cache exists to
# avoid. Only read on platforms that need it, and only for files.
_DIGEST_BYTES = 16


def _content_digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.blake2b(f.read(), digest_size=_DIGEST_BYTES).digest()
    except OSError:
        return None


def _stamp(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    # ctime and inode too: (mtime, size) alone collides on a same-size
    # rewrite within one timestamp tick or under `cp -p`; ctime cannot be
    # set back, and os.replace() changes the inode.
    stamp = (st.st_mtime_ns, st.st_size, st.st_ctime_ns, st.st_ino)
    # Where ctime cannot be trusted as a tiebreak, hash the bytes instead.
    # Directories are stamped too (a sibling appearing must invalidate), and
    # they have no contents to read, so this applies to files only -- a
    # directory's size and mtime do move when an entry is added or removed,
    # which is the property the sibling stamp actually relies on.
    if _CTIME_IS_CREATION_TIME and not stat.S_ISDIR(st.st_mode):
        stamp += (_content_digest(path),)
    return stamp


def compiled(owner: str, path, fullname: str, fixer_key, sibling_dirs: Iterable,
             build: Callable[[], object]):
    """The code object for `path`, from `build()` on a miss.

    `owner` names the loader twin that builds it, so the production loader
    never runs code the test twin compiled (or vice versa). `fixer_key` is
    whatever else the transforms were parameterised by (the
    implicit-relative fixer's package and self name).
    """
    validity = (_stamp(path), fixer_key,
                tuple((str(d), _stamp(d)) for d in sibling_dirs))
    key = (owner, str(path), fullname)
    hit = _cache.get(key)
    if hit is not None and hit[0] == validity:
        return hit[1]
    code = build()
    _cache[key] = (validity, code)
    return code


def clear() -> None:
    _cache.clear()
