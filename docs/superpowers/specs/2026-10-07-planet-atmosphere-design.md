# Planet atmosphere — design

**Status:** approved in conversation 2026-10-07 · branch `feat/planet-atmosphere`, stacked on `feat/planet-geosphere` (82d8cf75)
**Programme:** sub-project 3 of the planet rendering programme.
- SP1 is the geosphere: spec `2026-10-06-planet-geosphere-design.md`. It is unmerged and kept as a milestone branch.
- SP2 is surface detail, now expected to be procedural detail over BC's colour maps rather than 4096² textures. It will add a `surface` key to this catalogue; the format here must not block that.

## 1. Goal

Planets catch light believably:
- a scattering halo past the limb that is brightest toward the sun;
- the planet's own surface hazing toward the atmosphere colour at grazing angles (a Fresnel limb);
- a softened, tinted terminator.

Airless bodies stay hard-edged. Which planets have an atmosphere, and how it looks, comes from a catalogue. This sub-project is **render-only**. Burn-up damage is future work and may read the catalogue's `thickness` later.

## 2. Facts this design rests on (BC SDK, measured 2026-10-06/07)

- **How BC identifies a planet.** Every environment body, moons included, is created by `App.Planet_Create(radius, nif_path)`. That is all 120 such calls in `Systems/` plus mission scripts; there is no moon factory.
  - A planet's only identity is the pair (set name, object name) given by `pSet.AddObjectToSet(pPlanet, "Haven")` into a set registered as `g_kSetManager.AddSet(pSet, "Vesuvi6")`. Missions look planets up the same way: `pSet.GetObject("Haven")`, `Planet_GetObject(pSet, name)`.
  - Object names are **not unique** across sets: "Moon 1" appears in Geble3, Geble4 and Vesuvi6.
- **Appearance comes from the NIF.** Apart from size, everything about a planet's look comes from its NIF, and NIFs are shared: `purpleplanet` 10 uses, `pinkgasplanet` 9, `bluerockyplanet` 9, and so on.
- **BC's own atmosphere data is gameplay-only.** Only 7 planets call `SetAtmosphereRadius`: Albirea 3, Geki, Inyo, Mori, Haven, Vesuvi6 Moon 1 and Geble3 Moon 1.
  - The value is absolute GU added to the radius. Its only reader is `AI/PlainAI/Intercept.py:283`, as an avoidance keep-out capped at 125.
  - No planet sets environmental damage.
  - Our maps scale planet radii 20× and leave the atmosphere radius unscaled.
  - None of this affects how a planet looks, and this design does not use it.
- **System maps already carry the key.** Map bodies hold `name` (the `AddObjectToSet` name) and `owner_region` (the set). `apply_map._region_body` joins them the way `pSet.GetObject` does.
- **Renderer inputs already exist.**
  - Sun world position and radius are pushed every frame (`set_suns` → `g_suns`).
  - `nebula_atmosphere.h` already implements Henyey-Greenstein phase functions and a tested reference march.
  - The geosphere's sphere-map branch in `opaque.frag` already has the body-frame sphere direction for each fragment.

## 3. Catalogue

### 3.1 File and keys

`native/assets/planets/atmospheres.json` is a project asset, resolved through the project asset root **when used**, never at import. It is one JSON object with two kinds of key:

- **NIF stem:** the basename of `Planet_Create`'s second argument with the extension removed, **case-folded** (scripts say `GreenPurplePlanet.nif`, the file is `GreenPurplePlanet.NIF`). Example: `"greenpurpleplanet"`. This is the default for every planet using that NIF.
- **`"<set>/<name>"`:** a per-planet override, using the exact set name and object name, case-sensitive as BC uses them. Example: `"Vesuvi5/Mori"`.

A bare object name is **not** a key, because it is ambiguous across sets.

### 3.2 Entry

The example below shows the format only; the `Vesuvi5/Mori` override does not ship (§3.4).

```json
{
  "pinkgasplanet":  {"color": "#FF9A96", "thickness": 0.06, "density": 1.4, "limb": 1.0},
  "rockyplanet":    {"atmosphere": false},
  "Vesuvi5/Mori":   {"color": "#C8C8D0", "thickness": 0.02, "density": 0.4, "limb": 0.6}
}
```

| Field | Meaning | Range |
|---|---|---|
| `color` | RELATIVE per-channel Rayleigh scattering strength (not a final tint), `#RRGGBB` sRGB, converted to linear, then normalised so its strongest channel is 1 (§5). The visible hue emerges from scattering: short paths lean toward the strongest channel, long paths (terminator, back-lit rim) redden | — |
| `thickness` | shell height as a fraction of the planet radius | (0, 0.25] |
| `density` | haze strength multiplier | [0, 4] |
| `limb` | surface Fresnel-limb strength | [0, 4] |
| `sunset_color` | optional terminator tint; defaults to `color` | — |
| `intensity` | shell-HALO brightness multiplier only (not the surface `limb` term above); optional, default **20.0 (tuned live by Mark 2026-10-07)** | [0, 50] |
| `mie` | grey Mie forward-lobe strength (Mie extinction = σ·`mie` in every channel, HG g = 0.76); optional, default **0.2** | [0, 4] |
| `atmosphere` | `false` means airless; any other fields are ignored | — |

An entry whose `atmosphere` is not `false` must have `color`, `thickness`, `density` and `limb`.

**Unknown keys inside an entry are rejected by validation**, so typos surface. SP2 adds `surface` by extending the validator; existing entries stay valid.

### 3.3 Lookup

`engine/planets/atmosphere.py`:

```python
resolve(set_name: str, obj_name: str, nif_path: str) -> Atmosphere | None
```

- It returns the `"<set>/<name>"` entry if present, else the NIF-stem entry, else `None`.
- `{"atmosphere": false}` gives `None`.
- A malformed entry warns **once** per key and gives `None`, so the planet is airless and the game never crashes over data.

`Atmosphere` is a frozen dataclass of linear-RGB tuples and floats.

The file is read once per process and cached. A developer-only `reload()` re-reads it, for tuning.

### 3.4 Seed content (stock NIF defaults)

These are tiers, to be tuned live:

| Tier | `thickness` | `density` | `limb` |
|---|---|---|---|
| thick | 0.06 | 1.4 | 1.0 |
| medium | 0.035 | 1.0 | 1.0 |
| thin | 0.02 | 0.5 | 0.8 |

| Tier | Stem → color |
|---|---|
| thick | `pinkgasplanet` #FF9A96 · `bluewhitegasplanet` #BFE6FF · `tangasplanet` #E8D2B0 · `gasgiant` #E6EADC |
| medium | `greenpurpleplanet` #9FB0FF · `purpleplanet` #8F93FF · `purplewhiteplanet` #A8A4FF · `aquaplanet` #8EC8FF · `planet` #87B4FF · `brownblueplanet` #9CC4FF · `snowplanet` #A8CCFF · `greenplanet` #C8D27A · `slimegreenplanet` #B8C87A · `bluegrayplanet` #9CC8E0 · `bluetanplanet` #9CC4FF · `turquoiseplanet` #8ED8E0 · `brightgreenplanet` #8EE0D0 · `earth` #87B4FF · `lavenderplanet` #B0A8FF |
| thin | `bluerockyplanet` #7F9CFF · `brownplanet` #E0B080 · `dryplanet` #F0DCB0 · `iceplanet` #CFE0FF · `redplanet` #E08A50 · `sulfurplanet` #E8E08A · `rootbeerplanet` #E8C8B0 · `redswirlplanet` #E09070 |
| none | `moon` · `rockyplanet` · `grayplanet` · `tanplanet` |

**No per-planet overrides ship.** BC's `SetAtmosphereRadius` set (Mori, Vesuvi6 Moon 1, Geble 3 has none) is gameplay data, and the look follows the texture.

A test asserts that every stock planet NIF stem has an entry. The stems are listed in the test, since the content root may be absent on CI.

## 4. Wiring (Python → renderer)

- **Hook.** All three realize paths (mission load, `realize_set_objects`, `_reconcile_celestial_instances`) call one helper, `_apply_planet_atmosphere(r_, iid, set_name, obj_name, nif_path)`, right after the planet instance is created. The helper calls `resolve`, then the new binding `r_.set_instance_atmosphere(iid, params_or_None)`.
  - For unmapped sets, `set_name` is the planet's set name and `obj_name` is `planet.GetName()`.
  - For map-drawn bodies, they are `body.owner_region` and `body.name`.
- **Native state.** `scenegraph::Instance` gains:

  ```cpp
  struct Atmosphere { bool enabled = false; glm::vec3 color; glm::vec3 sunset_color;
                      float thickness, density, limb; };
  ```

  It defaults to disabled, so every existing instance is unchanged. `set_instance_atmosphere(iid, None)` disables it.
- **Sun direction, per planet.** The unit vector from the planet's world centre toward the nearest sun in `g_suns`, in render space. With no sun, it falls back to directional light 0's direction. Colour and intensity come from directional light 0.
- **Toggle.** `engine/planet_atmosphere.py` follows the `engine.planet_geosphere` mould: `enabled()` / `set_enabled()`, default **on**, read when used.
  - It appears in Developer Options → Environments as "Planet Atmospheres (off = airless; applies to planets realized after toggling)".
  - When off, the helper passes `None`.
  - `tests/conftest.py` resets it.
- **Teardown.** `teardown_set_objects` drops only the torn-down set's entries from the live registry, via `clear_live_for_set(pSet.GetName())` — not the whole registry — so a different set's live planets are unaffected by one set tearing down.

## 5. Shell pass (new `native/src/renderer/atmosphere_pass.{h,cc}`, shaders `atmosphere.{vert,frag}`)

**Order.** It draws in **phase 2** (`render_space_vfx`), right after `target.bind()` — before dust, rock fade, nebula, lens flares and weapons — so it samples `target.depth_texture()` to end the march at the nearest opaque surface. It runs **per drawn camera**, so the bridge viewscreen render target gets it too. The depth texture is detached from the bound FBO while sampled (reading and writing the same attachment in one draw is a feedback loop) and re-attached immediately after.
- Depth test **off**; depth writes **off** (the march, not a depth compare, decides where the haze ends).
- Blending is additive (`GL_ONE, GL_ONE`) into the HDR target.

**Geometry.** One unit geosphere (`assets::build_geosphere(4, 1.0)`) is uploaded once. Each enabled-atmosphere instance draws it at the planet's world centre (`world · sphere_map.center_body`), scaled to `R_top = R·(1 + thickness)`, where R = `sphere_map.radius` × instance scale.
- Front faces are drawn while the camera is outside `R_top`.
- Back faces are drawn while it is inside.

Instances whose model has no `sphere_map` are skipped, so the atmosphere requires the geosphere variant.

**Fragment.** Per pixel:
1. Find the view ray's segment inside the shell sphere `R_top` and outside the planet sphere `R`. The segment ends at the planet surface if the ray hits it, and starts at the camera if the camera is inside the shell.
2. March **8** samples. Density is `exp(−h / H)`, with `h` the height above `R` and scale height `H = 0.25·thickness·R`.
3. At each sample, light reaching it is `exp(−τ_sun)`. `τ_sun` is a **6**-sample midpoint march toward the sun (D3); it is set to large when the sun ray hits the planet, so the night side gets no in-scatter.
4. In-scatter is **chromatic Rayleigh plus a grey Mie forward lobe** (2026-10-07, approved by Mark). With `σ = density / (thickness·R)`:
   - `β_r = color / max(color.r, color.g, color.b)` (zero for an all-zero colour, never NaN); Rayleigh extinction per channel `σ_r = σ·β_r`.
   - Mie extinction `σ_m = σ·mie`, the same in every channel, sharing the density profile ρ.
   - Total extinction per channel `σ_r + σ_m`; the view and sun optical depths are RGB. `T = exp(−(τ_view_mid + τ_sun))` per channel.
   - In-scatter = `Σ ρ·σ_r·T·Δs · 3/(16π)(1+c²)  +  Σ ρ·σ_m·T·Δs · HG(0.76, c)`, `c = dot(view, sun)`. There is **no** final multiply by `color` — the hue comes from the coefficients, so a blue `color` gives a blue sunlit halo and a reddened terminator / back-lit rim.
5. Output `in_scatter · sun_color · sun_intensity · intensity`, where `sun_color` is directional light 0's colour (§4) and `intensity` is the catalogue entry's shell-halo multiplier (default 20.0, §3.2). The raw in-scatter saturates at ~0.06 at the lit limb regardless of tier (density/thickness are optically saturated there), against a sun colour of ~1 — about a sixth of the lit surface, invisible after tonemapping — so `intensity` is the only knob that makes the halo visible; it must be applied **before** the finite/clamp guard below, as a flat multiply on the final colour. It must be finite: NaN feeds bloom and produces black squares, so the shader guards both degenerate intersections and zero-length segments.

**CPU twin.** The march lives as a pure C++ function in `atmosphere_math.{h,cc}` (`renderer` library, GL-free): ray-shell segment, optical depth and in-scatter. The shader mirrors it, as `nebula_atmosphere.h` is mirrored, so tests pin the numbers.

## 6. Surface term (`opaque.frag`, sphere-map branch only)

New uniforms, set by `draw_model` only on a sphere-LOD draw of an instance whose atmosphere is enabled. Every other draw sets `u_atmo_enabled = 0`, because uniforms persist between draws.

```glsl
uniform int   u_atmo_enabled;
uniform vec3  u_atmo_color;         // linear
uniform vec3  u_atmo_sunset;        // linear
uniform float u_atmo_limb;
uniform vec3  u_atmo_sun_dir_ws;    // per planet, from §4
```

When it is on:
- **Limb haze.** `f = pow(1 − max(dot(n, V), 0), 3) · u_atmo_limb`, lit by `max(dot(n, L), 0)` plus a small wrap. Mix the lit result toward `u_atmo_color · sun_color` by `clamp(f, 0, 1)`.
- **Terminator.** With `x = dot(n, L)`, multiply the lit colour by `mix(vec3(1), u_atmo_sunset, smoothstep(0.25, 0.0, x) · step(-0.1, x) · 0.6)`, so a band near the terminator takes the sunset tint.

With `u_atmo_enabled == 0`, every existing path is byte-identical. The term runs after lighting and before the emissive and glow composite. No new derivatives are added, so the discard/derivative ordering is unchanged.

## 7. Developer tuning

- **Dial group.** Developer-only, registered with `engine.dev_dial_groups.register_group` as `"atmosphere"`, with dials `thickness`, `density`, `limb`, `color_r`, `color_g`, `color_b`, `intensity` (step 0.5, [0, 50]), `mie` (step 0.05, [0, 4]).
  - The dials edit the **catalogue entry** the planet **nearest the player** (by surface distance) resolved to — not just that one instance — and re-push the updated `Atmosphere` to every live planet sharing that entry (D4), since the override lives on the catalogue entry, not the instance.
  - The live values print through the group's existing report.
- **Saving.** Edits are not written back to JSON. Reload is a Developer Options **action row** ("Reload Planet Atmospheres", D2), not a keybinding, and the tuned numbers are copied into the JSON by hand. A save action is out of scope.

## 8. Out of scope

- Burn-up and environmental damage.
- Clouds.
- Scaling or using BC's gameplay `AtmosphereRadius`.
- Mod-supplied catalogue entries: the format allows a later merge, but nothing merges today.
- Multiple scattering.
- Atmospheric extinction of the sun's own light, and the effect on lens flares.
- The `surface` key (SP2).
- Atmospheres on planets without the geosphere variant, i.e. the developer toggle off, or a modded non-sphere NIF.

## 9. Testing

**Python:**
- **`resolve`:**
  - set/name wins over the stem;
  - the stem is case-folded from a `.nif` or `.NIF` path;
  - `atmosphere: false` gives `None`;
  - missing gives `None`;
  - a malformed entry warns once and gives `None`;
  - an unknown field is rejected;
  - hex colour converts to linear.
- **Catalogue file:** validates, and every listed stock stem is present.
- **Helper:** each realize path calls `set_instance_atmosphere` with the resolved params when enabled, and `None` when disabled. Fakes mirror the real binding signature.
- **Developer Options:** the toggle row and snapshot (the existing `test_every_setting_is_in_the_render_snapshot`).
- **Dial group:** registers; a step changes the nearest planet's params and re-pushes them.

**C++, GL-free (`atmosphere_math`):**
- ray-shell segment cases: miss; hit the shell only; hit the planet; camera inside the shell; tangent;
- optical depth matches a 256-step numerical reference within 5% (D3);
- in-scatter is zero on the night side, behind the planet;
- output is finite for degenerate inputs.

**C++, GL:**
- A geosphere planet with an atmosphere and the sun along +X: a pixel just outside the limb on the sun side is brighter than the mirrored pixel on the far side.
- No NaN or Inf anywhere in an HDR readback, both with the camera outside and with the camera inside the shell.
- With the atmosphere disabled, the frame matches a draw without the pass, pixel for pixel.
- The `u_atmo_enabled` leak guard: a non-atmosphere draw after an atmosphere draw reads 0.
- Every pre-existing `FrameTest` / `HullClipTest` / `HullFieldClipTest` still passes.

**Live (Mark, main checkout):** orbit Haven (medium), a pink gas giant (thick) and a moon (none); tune with the atmosphere dials.
