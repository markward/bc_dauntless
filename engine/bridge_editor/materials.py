"""Per-bridge document -> per-mesh material overrides (spec
2026-10-08-bridge-emitters §9.2 source B). -1.0 = no override for a channel."""


def overrides(doc, matched):
    out = []
    for key, mesh in matched.items():
        mat = doc["shapes"].get(key, {}).get("material")
        if not mat:
            continue
        out.append((int(mesh), float(mat.get("roughness", -1.0)),
                    float(mat.get("metalness", -1.0))))
    return sorted(out)
