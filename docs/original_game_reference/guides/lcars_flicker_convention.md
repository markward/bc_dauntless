# Bridge LCARs Flicker Convention

> **TL;DR.** When mission scripts call `pBridgeObject.FlickerLCARs(duration)`
> (e.g. on smoke / spark / explosion bridge effects), the engine modulates
> the emissive component of an `NiMaterialProperty` attached to the **`LCARs`
> NiNode** of the bridge model. NIF property inheritance propagates that
> modulation to every descendant surface, which is why the convention only
> needs a single named container and a parent-level material — no per-mesh
> tagging, no controller blocks. The 3DS Max NIF exporter
> (`niftools/max_nif_plugin`) can't produce this layout natively, which is
> why hand-modeled mod bridges almost never flicker correctly.

This document records the convention that distinguishes flicker-affected
geometry in BC interior bridge models, why the standard export tooling
doesn't produce it, and how to post-process an exported NIF to add the
missing structure.

---

## How the engine triggers it

Engine method, exposed to Python as:

```python
BridgeObjectClass.FlickerLCARs = new.instancemethod(
    Appc.BridgeObjectClass_FlickerLCARs, None, BridgeObjectClass)
```

Mission / bridge-effect scripts call it from `bridgeeffects.py`:

```python
# sdk/Build/scripts/Bridge/bridgeeffects.py
def CreateSmoke(fDuration):
    ...
    pBridgeObject.FlickerLCARs(2.0)

def CreateSpark(fDuration):
    ...
    pBridgeObject.FlickerLCARs(3.0)

def CreateExplosion(fDuration):
    ...
    pBridgeObject.FlickerLCARs(4.0)
```

There is no setup or registration code on the Python side — the engine
function locates the relevant geometry on its own using the NIF structure.

A sister method, `BridgeObjectClass.TurnLCARsOff()`, uses the same
selector to disable flickering surfaces wholesale.

---

## What the engine selects (the convention)

The two stock bridges that flicker — `game/data/Models/Sets/DBridge/Dbridge.NIF`
and `game/data/Models/Sets/EBridge/EBridge.nif` — share a single
distinctive structural pattern:

1. There is a `NiNode` named **exactly `"LCARs"`** (capital L, C, A, R;
   lowercase s) somewhere in the scene tree.
2. That `NiNode`'s **own `property_links` list** contains two properties:
   - An `NiMaterialProperty` whose **emissive** color is `(1.0, 1.0, 1.0)`
     (full white). Other fields: `flags=0x0001`, `ambient=(1,1,1)`,
     `diffuse=(1,1,1)`, `specular=(0,0,0)`, `glossiness=4.0`, `alpha=1.0`.
   - An `NiVertexColorProperty` with `flags=0x0000`, `vertex_mode=0`
     (`IGNORE`), and **`lighting_mode=1`** (`E_AMB_DIF`).
3. The descendant geometry under `"LCARs"` carries only its own
   `NiTextureProperty` (texture link). No per-mesh `NiMaterialProperty`,
   `NiAlphaProperty`, or `NiZBufferProperty` overrides.

NIF property inheritance does the rest: every descendant inherits the
parent's material and vertex-color properties unless explicitly overridden.

The engine appears to flicker by modulating the emissive RGB of the
parent `NiMaterialProperty` over `duration` seconds; inheritance broadcasts
that modulation to the entire subtree.

### Faction bridges that *don't* flicker

Verified with `scan_nifs` and a tree-walker (every interior bridge model
in stock BC):

| File | LCARs node? | Flickers in-game? |
|---|---|---|
| `Dbridge.NIF` | ✅ (6 children) | ✅ |
| `EBridge.nif` | ✅ (13 children) | ✅ |
| `cardbridge.NIF` | ❌ | n/a (enemy bridge, not player) |
| `kessokbridge.NIF` | ❌ | n/a |
| `romulanbridge.NIF` | ❌ | n/a |
| `BOPbridge.NIF` | ❌ | n/a |
| `ferengibridge.NIF` | ❌ | n/a |

Only the two player-faction interior bridges include the convention.

### Other "_LCARS" / "lcars" elements in the file

Stock BC bridges contain additional `NiNode`s named with LCARS-related
strings (`turboliftLCARS`, `Lcars Schematic left`, `Material: consoleLCARS`).
These are *under* the `LCARs` parent and inherit the parent's properties —
they are recipients of the flicker, not separate selectors.

The engine selector is the single named container `"LCARs"`, not a name
substring match.

---

## Why `max_nif_plugin` doesn't produce the convention

3DS Max's data model attaches materials to **meshes**, not to **dummy /
group nodes**. When you build a model with a dummy named `LCARs`, parent
your console / display meshes under it, give those meshes their materials,
and run the niftools `max_nif_plugin` exporter, the resulting NIF has:

- The dummy exported as a `NiNode` with **empty `property_links`**
- Each child mesh exported as `NiTriShape` with its own `NiMaterialProperty`,
  `NiTextureProperty`, etc.

The plugin has no UI control or export option that says "lift this material
to the parent group" or "attach this property to this dummy node." A
modder using the standard export pipeline ends up with the right *tree
shape* but no parent-level material for the engine to flicker — the tree
looks correct but renders normally because there's nothing under the
`LCARs` `NiNode` for `FlickerLCARs()` to mutate.

This is why community-built bridges (which there were many of in the
modding scene) almost never had working flicker, even when modders
correctly identified that the geometry needs to be under a node named
`LCARs`.

---

## Post-processing recipe

Run a script after exporting from Max to attach the missing properties to
the `LCARs` `NiNode`. Two plausible toolchains:

### Option A — pyffi (recommended for BC modders)

[pyffi](https://github.com/niftools/pyffi) is the niftools Python library
the modding community already uses for various tooling. The script below
loads a NIF, finds every `NiNode` named exactly `"LCARs"`, and attaches
the convention properties if they are missing.

```python
#!/usr/bin/env python
"""
add_lcars_flicker.py — post-process a niftools-exported NIF so its
"LCARs"-named nodes match the stock BC flicker convention.

Idempotent: rerunning on an already-fixed file is a no-op.

Usage:
    python add_lcars_flicker.py <input.nif> <output.nif>
"""
import sys
from pyffi.formats.nif import NifFormat


LCARS_NODE_NAME = "LCARs"  # exact match — case matters

def make_material_property():
    """Emissive=(1,1,1) glow material that the engine modulates."""
    m = NifFormat.NiMaterialProperty()
    m.flags = 0x0001
    m.ambient_color.r = m.ambient_color.g = m.ambient_color.b = 1.0
    m.diffuse_color.r = m.diffuse_color.g = m.diffuse_color.b = 1.0
    m.specular_color.r = m.specular_color.g = m.specular_color.b = 0.0
    m.emissive_color.r = m.emissive_color.g = m.emissive_color.b = 1.0
    m.glossiness = 4.0
    m.alpha = 1.0
    return m

def make_vertex_color_property():
    """vertex_mode=IGNORE, lighting_mode=E_AMB_DIF — required so the
    inherited material drives lighting on descendants."""
    v = NifFormat.NiVertexColorProperty()
    v.flags = 0x0000
    v.vertex_mode = 0   # SOURCE_IGNORE
    v.lighting_mode = 1 # LIGHTING_E_AMB_DIFF
    return v

def has_property_of_type(node, prop_type):
    return any(isinstance(p, prop_type) for p in node.properties)

def fix_lcars_node(node, root):
    """Append the two flicker properties to `node` if missing."""
    changed = False
    if not has_property_of_type(node, NifFormat.NiMaterialProperty):
        node.add_property(make_material_property())
        changed = True
    if not has_property_of_type(node, NifFormat.NiVertexColorProperty):
        node.add_property(make_vertex_color_property())
        changed = True
    return changed

def main(in_path, out_path):
    data = NifFormat.Data()
    with open(in_path, "rb") as f:
        data.read(f)

    fixed_nodes = 0
    for root in data.roots:
        for block in root.tree():
            if not isinstance(block, NifFormat.NiNode):
                continue
            if block.name and block.name.decode("ascii", errors="replace") == LCARS_NODE_NAME:
                if fix_lcars_node(block, root):
                    fixed_nodes += 1

    if fixed_nodes == 0:
        print("No LCARs nodes needed fixing (already correct, or none found).")
    else:
        print(f"Attached flicker properties to {fixed_nodes} LCARs node(s).")

    with open(out_path, "wb") as f:
        data.write(f)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
```

> **API notes:** field names (`emissive_color`, `diffuse_color`,
> `vertex_mode`, `lighting_mode`) follow pyffi's CamelCase→snake_case
> convention from `nif.xml`. `node.add_property(p)` resizes
> `properties_link` and appends `p` in one call. Refer to the pyffi NIF
> bindings for exact identifiers if a version mismatch surfaces — the
> structural intent is what matters: append a `NiMaterialProperty` (with
> emissive RGB at 1.0) and a `NiVertexColorProperty` (with
> `lighting_mode = 1`) to the `LCARs` node's property list.

### Option B — niflib (C++)

For build pipelines that already link niflib (e.g. an asset-cooker step):

```cpp
#include <niflib.h>
#include <obj/NiNode.h>
#include <obj/NiMaterialProperty.h>
#include <obj/NiVertexColorProperty.h>
#include <obj/NiObject.h>

#include <fstream>
#include <iostream>
#include <vector>

using namespace Niflib;

static const std::string kLcarsNodeName = "LCARs";

NiMaterialPropertyRef make_material() {
    auto m = new NiMaterialProperty();
    m->SetFlags(0x0001);
    m->SetAmbientColor (Color3(1, 1, 1));
    m->SetDiffuseColor (Color3(1, 1, 1));
    m->SetSpecularColor(Color3(0, 0, 0));
    m->SetEmissiveColor(Color3(1, 1, 1));
    m->SetGlossiness(4.0f);
    m->SetAlpha(1.0f);
    return m;
}

NiVertexColorPropertyRef make_vc() {
    auto v = new NiVertexColorProperty();
    v->SetFlags(0x0000);
    v->SetSourceVertexMode(SRC_VERT_MODE_IGNORE);   // 0
    v->SetLightingMode    (LIGHT_MODE_E_AMB_DIFF);  // 1
    return v;
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "usage: add_lcars_flicker <in.nif> <out.nif>\n";
        return 2;
    }
    NifInfo info;
    auto root = ReadNifTree(argv[1], &info);

    std::vector<NiObjectRef> all;
    GatherAll(root, all);  // walk the tree

    int fixed = 0;
    for (auto& o : all) {
        auto node = DynamicCast<NiNode>(o);
        if (!node || node->GetName() != kLcarsNodeName) continue;

        bool has_mat = false, has_vc = false;
        for (auto& p : node->GetProperties()) {
            if (DynamicCast<NiMaterialProperty>(p))    has_mat = true;
            if (DynamicCast<NiVertexColorProperty>(p)) has_vc  = true;
        }
        if (!has_mat) node->AddProperty(make_material());
        if (!has_vc)  node->AddProperty(make_vc());
        if (!has_mat || !has_vc) ++fixed;
    }

    WriteNifTree(argv[2], root, info);
    std::cout << "Fixed " << fixed << " LCARs nodes\n";
    return 0;
}
```

`GatherAll` is a small recursive helper (or use `Niflib::SearchObjectsByType<NiNode>`
if your niflib build exports it).

### Option C — open_stbc parser + custom writer

Not yet supported. The `nif::` library in this project is read-only by
design (Phase 2 sub-project 1). Adding write support is a follow-on
sub-project; until then, use pyffi or niflib.

---

## Verifying the fix

After running the post-process script, you can confirm the structure
matches the stock-bridge convention with the open_stbc inspection tool
or any NIF inspector that decodes legacy v3.x. The manual verification
checklist:

1. The `NiNode` named `"LCARs"` has at least 2 entries in its
   property_links list.
2. One of them is an `NiMaterialProperty` with `emissive=(1,1,1)`.
3. One of them is an `NiVertexColorProperty` with `lighting_mode=1`.
4. The descendant `NiTriShape` blocks under `"LCARs"` do **not** carry
   their own `NiMaterialProperty` (otherwise the per-mesh material
   overrides the inherited flicker material).

If you have the BC asset corpus available, you can sanity-check by
running the open_stbc scan harness:

```bash
./build/native/tools/scan_nifs/scan_nifs path/to/your/mod/Sets/MyBridge/
```

It should report `reached End Of File: N`. The parser is structural-only;
it does not validate the convention, but if your file parses cleanly the
post-process didn't corrupt the structure.

In-game verification: load the bridge, trigger any combat/damage event
that calls one of the bridge effects (smoke/spark/explosion), and watch
your console / wall LCARS panels for the flicker.

---

## Caveats

- **Name is case-sensitive.** `"LCARs"` (capital L, C, A, R; lowercase
  s) is the exact name in stock files. `"LCARS"`, `"lcars"`, `"Lcars"`
  will not match the engine's selector.
- **Per-mesh material overrides break inheritance.** If your meshes
  carry their own `NiMaterialProperty` (the niftools plugin's default
  export behaviour), the inherited flicker material is overridden on
  those meshes. The post-process script above does not strip per-mesh
  materials — for a stock-faithful result you may need to either delete
  per-mesh `NiMaterialProperty` blocks from `LCARs` descendants, or
  ensure your Max materials use a "transparent" / pass-through emissive
  setting that doesn't fight the parent.
- **Property order can matter.** The stock bridges have
  `NiMaterialProperty` before `NiVertexColorProperty` in the
  `property_links` list. The pyffi script preserves insertion order via
  `add_property()`; the niflib version is the same. Engines historically
  haven't cared about property order, but if flicker doesn't activate
  after the post-process, this is a low-likelihood thing to check.
- **`TurnLCARsOff()` shares the selector.** Anything you make flicker
  via this convention will also turn off when a script calls
  `pBridgeObject.TurnLCARsOff()`. There is no way to opt one out
  without splitting the geometry across two named container nodes,
  which the engine wouldn't recognize.
- **Convention is engine-internal, not documented in the BC SDK.** This
  writeup is reverse-engineered from inspecting `Dbridge.NIF` /
  `EBridge.nif` plus reading `bridgeeffects.py`. It matches the observed
  in-game behaviour and the structural difference between the two
  flicker-capable bridges and the five non-flickering enemy bridges,
  but the engine's exact `FlickerLCARs` implementation is in the
  closed-source `Appc.dll` and could in principle do something more
  complex that we haven't observed.

---

## Provenance

This convention was identified during open_stbc Phase 2 sub-project 1
(NIF loader). The `scan_nifs` harness and a small custom inspector
(`/tmp/dump_props.cc`-style tools) were used to compare the LCARs
substructure across all stock bridge files in `game/data/Models/Sets/`.
The Python-side selector — `BridgeObjectClass.FlickerLCARs` —
was located by grepping the BC SDK scripts for damage/effect
trigger paths. The two pieces together (engine method + structurally
distinctive NIF subtree) produced this writeup.
