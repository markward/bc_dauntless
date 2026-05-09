"""Bootstrap module loaded by open_stbc_host to verify embedding works.

Phase F replaces the `run` body with the real mission/render loop. The banner
function is the Phase A liveness check the host binary calls right after
Py_InitializeEx.
"""

def banner() -> str:
    return "open_stbc host alive"
