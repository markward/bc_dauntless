"""The SDK modules the warp's SDK half actually reads, for tests to patch."""


def warp_missionlib():
    """The MissionLib that SDK WarpSequence.WaitForQueued reads its
    g_idMasterSequenceObj from. Many tests purge sys.modules["MissionLib"] and
    re-import it, but WarpSequence keeps the module object it imported first,
    so patching the freshly imported MissionLib misses it -- patch this one."""
    import WarpSequence
    return WarpSequence.MissionLib
