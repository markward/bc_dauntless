"""Give every ship in the scene a rig, so the native subsystem stage hands
its ARTICULATION piece to Python every tick (a rigless ship's is skipped
natively once tick_ship has found it rigless; Task 6)."""
import App

from engine.appc import articulated_part, articulation
from engine.appc.ship_iter import iter_non_rock_ships


def rig_all_ships():
    """Snapshot a one-part rig for each ship's leaf; returns the previous
    snapshot table for `articulated_part.restore`."""
    before = dict(articulated_part._BY_LEAF)
    for leaf in sorted({articulation.leaf_for(s)
                        for s in iter_non_rock_ships()}):
        part = articulated_part.ArticulatedPartProperty_Create("test wing")
        part.SetStateAngle("cruise", 10.0)
        part.SetStateAngle("red", 40.0)
        App.g_kModelPropertyManager.RegisterLocalTemplate(part)
        articulated_part.snapshot_for_leaf(leaf)
    return before
