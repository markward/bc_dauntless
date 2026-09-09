// Dump every NiMaterialProperty in a NIF: ambient / diffuse / specular /
// emissive / glossiness / alpha.
//
// Written while diagnosing a modded ship that rendered blown-out white. The
// opaque shader's self-illumination term is
//     u_emissive_scale * (u_emissive_color + glow_rgb * glow.a * ...)
// so a material authored with a high emissive washes the hull out no matter
// what its glow map's alpha says. A 3ds Max export left at 100%
// self-illumination does exactly that, and nothing else in the toolchain
// surfaces the value.
#include <nif/file.h>
#include <nif/block.h>

#include <cstdio>
#include <variant>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: inspect_materials <file.nif>\n");
        return 2;
    }
    nif::File f = nif::load(argv[1]);

    int found = 0;
    for (std::size_t i = 0; i < f.blocks.size(); ++i) {
        const auto* m = std::get_if<nif::NiMaterialProperty>(&f.blocks[i]);
        if (!m) continue;
        ++found;
        const bool hot = m->emissive.r > 0.5f || m->emissive.g > 0.5f ||
                         m->emissive.b > 0.5f;
        std::printf(
            "[%zu] NiMaterialProperty '%s'\n"
            "      ambient  = (%.3f, %.3f, %.3f)\n"
            "      diffuse  = (%.3f, %.3f, %.3f)\n"
            "      specular = (%.3f, %.3f, %.3f)\n"
            "      EMISSIVE = (%.3f, %.3f, %.3f)%s\n"
            "      glossiness = %.3f   alpha = %.3f\n",
            i, m->obj.name.c_str(),
            m->ambient.r, m->ambient.g, m->ambient.b,
            m->diffuse.r, m->diffuse.g, m->diffuse.b,
            m->specular.r, m->specular.g, m->specular.b,
            m->emissive.r, m->emissive.g, m->emissive.b,
            hot ? "   <-- HIGH: this self-illuminates the whole surface" : "",
            m->glossiness, m->alpha);
    }
    if (found == 0) std::printf("(no NiMaterialProperty blocks)\n");
    return 0;
}
