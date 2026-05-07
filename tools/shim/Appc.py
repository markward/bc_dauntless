# tools/appc_logger.py
#
# Appc logging shim for Bridge Commander instrumentation.
# Written in Python 1.5-compatible syntax (the version embedded in stbc.exe).
#
# WHAT IT DOES
# ------------
# Intercepts every call to the Appc C extension (the SWIG-generated engine
# interface) and writes a timestamped log entry. Passes every call through
# to the real Appc.pyd unchanged, so the game runs normally.
#
# DEPLOYMENT
# ----------
# 1. Create a shim directory alongside stbc.exe, e.g. Z:\path\to\game\shim\
# 2. Copy this file there as Appc.py  (the filename must be exactly Appc.py)
# 3. Launch BC with PYTHONPATH set so the shim dir comes first:
#
#    PYTHONPATH="Z:\path\to\game\shim" wine stbc.exe
#
#    On Mac via Wine, set the env var in the terminal before running:
#
#    export WINEPATH="Z:\path\to\game\shim"
#    PYTHONPATH="/path/to/game/shim" wine stbc.exe
#
#    Or inline:
#    PYTHONPATH="/path/to/game/shim" wine /path/to/game/stbc.exe
#
# 4. Play normally for a few minutes.  The log is written to appc_session.log
#    in the working directory (usually the same folder as stbc.exe).
#
# HOW IT WORKS
# ------------
# Python finds our Appc.py before the real Appc.pyd because our shim
# directory is first in sys.path. The shim temporarily removes itself from
# sys.path, imports the real Appc.pyd under the name _real_Appc, then
# replaces itself in sys.modules with an _AppcModuleShim instance. From
# that point on, every attribute access on the "Appc" module goes through
# the shim's __getattr__, which wraps each callable with a logger.
#
# Python 1.5 has no lexical closures (those arrived in 2.1). Wrapping is
# done via a _CallWrapper class instance so each wrapper holds its own
# references to the real function and its name.
#
# LOG FORMAT
# ----------
# Tab-separated columns, one call per line:
#   elapsed_seconds  frame_number  function_name  args_repr
#
# elapsed_seconds  wall-clock seconds since session start, 6 decimal places
# frame_number     value of the last seen TGSystemWrapper_GetUpdateNumber
#                  return value. 0 until the first GetUpdateNumber call.
# function_name    the Appc attribute name that was called (or ATTR:/SET: for
#                  non-callable accesses and assignments)
# args_repr        repr() of each argument, comma-separated, truncated to 80
#                  chars per argument
#
# For GetUpdateNumber the return value is appended as a 5th column so you
# can trivially reconstruct frame boundaries:
#   0.016700  0  TGSystemWrapper_GetUpdateNumber  <swig ...>  -> 1
#
# ANSWERING THE OPEN QUESTIONS
# ----------------------------
# Q1 (tick rate):
#   grep for TGSystemWrapper_GetUpdateNumber, extract col 1 (timestamp)
#   for consecutive lines where col 5 increments by 1. Average the deltas.
#
# Q2 (subsystem ordering):
#   For a fixed frame number, list all rows in order. The sequence of
#   function names shows what fires in what order within each tick.
#
# OQ-4.2 (event dispatch):
#   grep for TGEventManager_AddEvent. Check whether the AddEvent call and
#   the next event handler invocation share the same frame number (immediate
#   dispatch) or differ (queued to next frame).
#
# OQ-2.1 (degradation formula):
#   During combat, filter for SetDisabledPercentage and physics parameter
#   reads (GetMaxAccel, GetCondition, etc.) to see how they track together.

import sys
import os
import time

# Diagnostic: write immediately on import so we know if Python found this file
# at all, independent of whether the rest of the shim succeeds.
try:
    _diag = open(os.path.join(os.getcwd(), 'shim_loaded.txt'), 'w')
    _diag.write('Appc shim loaded\n')
    _diag.close()
except Exception:
    pass

# ---------------------------------------------------------------------------
# 1. Load the real Appc extension
# ---------------------------------------------------------------------------
# Appc is compiled into stbc.exe as a built-in module (no Appc.pyd exists).
# Built-in modules are normally found before .py files, but because Python
# has already started executing this file, it has stored a partial module
# object in sys.modules['Appc']. A naïve "import Appc" would return that
# partial object rather than the real built-in.
#
# Fix: remove ourselves from sys.modules and from sys.path before importing,
# so Python falls through to the built-in module table.

_shim_dir = os.path.normcase(os.path.abspath(os.path.dirname(__file__)))

# Remove our partially-initialised self from sys.modules
if sys.modules.has_key('Appc'):
    del sys.modules['Appc']

# Remove shim dir from sys.path so we don't load this file again
_saved_path = sys.path[:]
_clean_path = []
for _p in sys.path:
    try:
        if os.path.normcase(os.path.abspath(_p)) != _shim_dir:
            _clean_path.append(_p)
    except Exception:
        _clean_path.append(_p)
sys.path = _clean_path

try:
    import Appc as _real_Appc
except ImportError:
    sys.path = _saved_path
    raise

sys.path = _saved_path

# ---------------------------------------------------------------------------
# 2. Logging infrastructure
# ---------------------------------------------------------------------------

_log_path = os.path.join(os.getcwd(), 'appc_session.log')
_log_file = open(_log_path, 'w')
_log_file.write('# elapsed_s\tframe\tfunction\targs\n')
_log_file.flush()

_t0 = time.time()

# Mutable containers so inner functions can update them (Python 1.5: no
# nonlocal, no closures — only global or mutable container workarounds).
_state = {
    'frame': 0,
    'flush_countdown': 32,
}


def _ts():
    return time.time() - _t0


def _fmt_args(args):
    parts = []
    for a in args:
        try:
            r = repr(a)
        except Exception:
            r = '<error>'
        if len(r) > 80:
            r = r[:77] + '...'
        parts.append(r)
    return ', '.join(parts)


def _write(name, args_repr, extra=''):
    line = '%.6f\t%d\t%s\t%s%s\n' % (
        _ts(), _state['frame'], name, args_repr, extra)
    _log_file.write(line)
    _state['flush_countdown'] = _state['flush_countdown'] - 1
    if _state['flush_countdown'] <= 0:
        _log_file.flush()
        _state['flush_countdown'] = 32


# ---------------------------------------------------------------------------
# 3. Per-call wrapper
# ---------------------------------------------------------------------------
# A class instance rather than a closure because Python 1.5 has no lexical
# closures. Each instance holds its own reference to the real function and
# its name.

class _CallWrapper:

    def __init__(self, func, name):
        self._func = func
        self._name = name

    def __call__(self, *args):
        args_repr = _fmt_args(args)

        # Special case: GetUpdateNumber tells us which frame we are in.
        # Log it with the return value so frame boundaries are unambiguous.
        if self._name == 'TGSystemWrapper_GetUpdateNumber':
            result = apply(self._func, args)
            _state['frame'] = result
            _write(self._name, args_repr, '\t-> %d' % result)
            return result

        _write(self._name, args_repr)
        return apply(self._func, args)

    def __repr__(self):
        return '<AppcLogger:%s>' % self._name


# ---------------------------------------------------------------------------
# 4. Module shim
# ---------------------------------------------------------------------------
# Replaces this module object in sys.modules so that every attribute access
# on the "Appc" module goes through __getattr__. This is the standard
# Python 1.5-era technique for module-level interception.

class _AppcModuleShim:

    def __init__(self, real):
        # Store in __dict__ directly to avoid triggering our own __setattr__
        self.__dict__['_real'] = real
        self.__dict__['_wrapper_cache'] = {}

    def __getattr__(self, name):
        cache = self.__dict__['_wrapper_cache']
        if cache.has_key(name):
            return cache[name]

        real = self.__dict__['_real']
        val = getattr(real, name)

        if callable(val):
            wrapper = _CallWrapper(val, name)
            cache[name] = wrapper
            return wrapper
        else:
            # Non-callable attribute (constant, enum value, etc.)
            # Log once on first access; don't cache so live changes are seen.
            _write('ATTR:' + name, repr(val)[:80])
            return val

    def __setattr__(self, name, value):
        _write('SET:' + name, repr(value)[:80])
        setattr(self.__dict__['_real'], name, value)


# Replace ourselves in sys.modules. After this line, any code that
# does "import Appc" or accesses the Appc module gets the shim.
sys.modules[__name__] = _AppcModuleShim(_real_Appc)
