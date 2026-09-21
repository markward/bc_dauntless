# Project-authored renderer textures

Resolved by the renderer through `renderer::project_asset_path()` — the root
is `<checkout>/native/assets`, pushed at boot by `engine/host_loop.py` via
`set_project_asset_root`. Nothing here is BC content and nothing here is
looked up under `game/`.

| File | Used by | Contract |
|---|---|---|
| `scuff_normal.png` (or `.tga`) | `opaque.frag:apply_scuffs` via `scuff_texture.cc` | Tiling tangent-space normal map of crumpled sheet metal, OpenGL +Y green (`kScuffFlipGreen` in the shader if not), 2048² recommended; z is re-derived from x/y at load. Absent ⇒ logged once, scuffs draw albedo only. |
