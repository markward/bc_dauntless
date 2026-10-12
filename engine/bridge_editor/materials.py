"""Meshes -> per-mesh roughness/metalness overrides from each mesh's resolved
material (spec §13.2; §9.2 source B): its object's link, else its texture's
material (lighting_doc.resolve). -1.0 = no override for a channel."""


def overrides(doc, resolved):
    out = []
    for mesh, name in resolved.items():
        mat = doc["materials"].get(name)
        if not mat or ("roughness" not in mat and "metalness" not in mat):
            continue
        out.append((int(mesh), float(mat.get("roughness", -1.0)),
                    float(mat.get("metalness", -1.0))))
    return sorted(out)
