"""After ``g_kLODModelManager`` is wired up, ship ``LoadModel()`` flows must
not record any LOD-related stub calls.

The gameloop harness flagged ``g_kLODModelManager.Contains`` as the #1 stub
call (242 invocations across 30 missions).  The root cause: every
``sdk/Build/scripts/ships/<Class>.py`` checks ``Contains`` before doing the
``Create`` + ``AddLOD`` + ``Load`` sequence.  Because the manager was a
``_NamedStub`` whose ``Contains()`` returned a truthy stub, the guard
``not Contains(...)`` evaluated False and the entire registration block was
silently skipped.

This test exercises a representative ship script's ``LoadModel`` and
asserts (a) the call records nothing in ``_stub_tracker`` and (b) the
manager actually captured the AddLOD data.
"""

import App
import ships.Galaxy as Galaxy
from engine.appc.lod_models import LODModel


LOD_STUB_NAMES = {
    "g_kLODModelManager.Contains",
    "g_kLODModelManager.Create",
    "g_kLODModelManager.Purge",
    # Chained off the _NamedStub Create() return — these would also surface
    # if Create returned a stub instead of a real LODModel.
    "AddLOD",
    "SetTextureSharePath",
    "Load",
    "LoadIncremental",
}


def test_ship_loadmodel_records_no_lod_stubs():
    App._stub_tracker.clear()
    App.g_kLODModelManager.Purge()
    App._stub_tracker.set_mission("regression")

    Galaxy.LoadModel()
    Galaxy.LoadModel()  # Second call must hit the Contains-true branch.

    App._stub_tracker.reset_mission()
    leaked = {name for (name, _, _) in App._stub_tracker.report()
              if name in LOD_STUB_NAMES}
    assert leaked == set(), (
        "LOD model SDK calls still hit _NamedStub: " + repr(leaked))


def test_loadmodel_populates_manager_state():
    App.g_kLODModelManager.Purge()
    Galaxy.LoadModel()

    model = App.g_kLODModelManager.Get("Galaxy")
    assert isinstance(model, LODModel)
    assert App.g_kLODModelManager.Contains("Galaxy")
    # Galaxy.py registers three LODs (high/med/low).
    assert [lod.filename for lod in model.lods] == [
        "data/Models/Ships/Galaxy/Galaxy.nif",
        "data/Models/Ships/Galaxy/GalaxyMed.nif",
        "data/Models/Ships/Galaxy/GalaxyLow.nif",
    ]
    # Switch-out distances from sdk/Build/scripts/ships/Galaxy.py:25-27.
    assert [lod.switch_out_distance for lod in model.lods] == [200.0, 400.0, 800.0]
    # Glow search string is the search-string mechanism used at runtime —
    # cf. project memory "BC glow maps come from AddLOD, not NIF".
    assert all(lod.glow_search == "_glow" for lod in model.lods)
    assert model.texture_share_path == "data/Models/SharedTextures/FedShips"
    assert model.loaded is True
    assert model.load_incremental is False


def test_preload_uses_load_incremental():
    App.g_kLODModelManager.Purge()
    Galaxy.PreLoadModel()

    model = App.g_kLODModelManager.Get("Galaxy")
    assert model.loaded is True
    assert model.load_incremental is True
