"""LODModelManager / LODModel — ship NIF registry used by every ship script.

Every ``sdk/Build/scripts/ships/<Class>.py`` follows the same shape::

    def LoadModel(bPreLoad = 0):
        pStats = GetShipStats()
        if (not App.g_kLODModelManager.Contains(pStats["Name"])):
            pLODModel = App.g_kLODModelManager.Create(pStats["Name"])
            pLODModel.AddLOD(FilenameHigh, 10, 200.0, ..., "_glow", None, None)
            pLODModel.AddLOD(FilenameMed,  10, 400.0, ..., "_glow", None, None)
            pLODModel.AddLOD(FilenameLow,  10, 800.0, ..., "_glow", None, None)
            pLODModel.SetTextureSharePath("data/Models/SharedTextures/FedShips")
            if bPreLoad == 0:
                pLODModel.Load()
            else:
                pLODModel.LoadIncremental()

The manager is a registry keyed by ship name so the AddLOD pass runs exactly
once per class — calling ``Create`` again would re-append LOD entries.

Headless Phase 1 doesn't open NIFs.  We record every parameter so later passes
(renderer host, asset-pipeline tests, glow lookup driven by ``AddLOD`` search
strings — see the project-memory note on glow maps coming from AddLOD rather
than NIF) can read structured ship→NIF metadata without re-parsing ship
scripts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# SWIG signature, from sdk/Build/scripts/App.py:4293 +
# the call sites in sdk/Build/scripts/ships/*.py:
#
#   AddLOD(filename, pickLeafSize, switchOutDist,
#          surfaceDmgRes, internalDmgRes, burnValue, holeValue,
#          glowSearch, specSearch, specSuffix)
@dataclass
class LODEntry:
    filename: str
    pick_leaf_size: int
    switch_out_distance: float
    surface_damage_resistance: float
    internal_damage_resistance: float
    burn_value: int
    hole_value: int
    glow_search: str | None
    specular_search: str | None
    specular_suffix: str | None


class LODModel:
    def __init__(self, name: str):
        self.name = name
        self.lods: list[LODEntry] = []
        self.texture_share_path: str | None = None
        # Tracks whether Load() / LoadIncremental() has been called.  Phase 1
        # doesn't open NIFs, so this is bookkeeping only; the renderer host
        # in Phase 2 will use it to decide what to push to the GPU.
        self.loaded = False
        self.load_incremental = False

    def AddLOD(self, filename, pick_leaf_size, switch_out_distance,
               surface_damage_resistance, internal_damage_resistance,
               burn_value, hole_value,
               glow_search=None, specular_search=None, specular_suffix=None):
        self.lods.append(LODEntry(
            filename=str(filename),
            pick_leaf_size=int(pick_leaf_size),
            switch_out_distance=float(switch_out_distance),
            surface_damage_resistance=float(surface_damage_resistance),
            internal_damage_resistance=float(internal_damage_resistance),
            burn_value=int(burn_value),
            hole_value=int(hole_value),
            glow_search=glow_search,
            specular_search=specular_search,
            specular_suffix=specular_suffix,
        ))

    def SetTextureSharePath(self, path: str) -> None:
        self.texture_share_path = str(path)

    def Load(self) -> None:
        self.loaded = True
        self.load_incremental = False

    def LoadIncremental(self) -> None:
        self.loaded = True
        self.load_incremental = True


class LODModelManager:
    def __init__(self) -> None:
        self._models: dict[str, LODModel] = {}

    def Contains(self, name: str) -> bool:
        return name in self._models

    # SWIG signature accepts trailing args (e.g. Asteroid.py passes a leaf
    # budget: ``Create(name, 10000)``; FedStarbase passes two).  Phase 1 has
    # no use for them but must accept them silently.
    def Create(self, name: str, *args) -> LODModel:
        model = LODModel(name)
        self._models[name] = model
        return model

    def Purge(self) -> None:
        self._models.clear()

    # Convenience for the renderer host and tests — not part of the SWIG API.
    def Get(self, name: str) -> LODModel | None:
        return self._models.get(name)
