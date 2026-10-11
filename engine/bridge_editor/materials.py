"""Objects -> per-mesh roughness/metalness overrides from each object's
material (spec §13.2; §9.2 source B). -1.0 = no override for a channel."""


def overrides(doc, matched):
    out = []
    for key, mesh in matched.items():
        name = doc["objects"].get(key, {}).get("material")
        mat = doc["materials"].get(name) if name else None
        if not mat or ("roughness" not in mat and "metalness" not in mat):
            continue
        out.append((int(mesh), float(mat.get("roughness", -1.0)),
                    float(mat.get("metalness", -1.0))))
    return sorted(out)
