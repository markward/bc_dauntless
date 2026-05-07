"""
Phase 1 shim for LoadBridge.

In the real game, LoadBridge.Load(bridge_name) loads a bridge NIF model and
registers the resulting SetClass under the name "bridge" in g_kSetManager.
In Phase 1 headless mode we just create an empty SetClass so that
g_kSetManager.GetSet("bridge") returns a valid object rather than None.
"""


def Load(bridge_name: str = ""):
    import App
    existing = App.g_kSetManager.GetSet("bridge")
    if existing:
        return existing
    pSet = App.SetClass_Create()
    App.g_kSetManager.AddSet(pSet, "bridge")
    # Add a placeholder bridge-model object so GetObject("bridge") returns
    # a real ObjectClass with GetAnimNode() rather than None.
    bridge_obj = App.ObjectClass()
    pSet.AddObjectToSet(bridge_obj, "bridge")
    return pSet


def CreateCharacterMenus(*args, **kwargs):
    """Phase 1 stub — bridge UI menus are not needed for headless logic testing."""
    pass
