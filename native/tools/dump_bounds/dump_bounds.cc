// Report the authored per-shape bounding spheres in a NIF.
//
// Written to answer one question: do BC's models actually carry non-zero
// NiTriShapeData::bound_radius? Everything downstream — compute_model_bounds,
// the per-ship cache, the collision/avoidance narrow phase — silently degrades
// to the model-wide sphere if they are all zero, and that degradation looks
// identical to "the feature isn't wired up".
#include <cstdio>
#include <exception>
#include <variant>

#include <nif/block.h>
#include <nif/file.h>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <file.nif> [more.nif ...]\n", argv[0]);
        return 2;
    }
    for (int i = 1; i < argc; ++i) {
        try {
            nif::File doc = nif::load(argv[i]);
            int shapes = 0, nonzero = 0;
            float max_r = 0.0f;
            for (const auto& b : doc.blocks) {
                if (const auto* d = std::get_if<nif::NiTriShapeData>(&b)) {
                    ++shapes;
                    if (d->bound_radius > 0.0f) ++nonzero;
                    if (d->bound_radius > max_r) max_r = d->bound_radius;
                }
            }
            std::printf("%-58s shapes=%-4d bounded=%-4d max_r=%.1f\n",
                        argv[i], shapes, nonzero, max_r);
        } catch (const std::exception& e) {
            std::printf("%-58s ERROR %s\n", argv[i], e.what());
        }
    }
    return 0;
}
