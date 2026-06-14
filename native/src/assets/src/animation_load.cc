// native/src/assets/src/animation_load.cc
#include <assets/animation.h>

#include <nif/file.h>

#include "animation_build.h"

namespace assets {

std::vector<AnimationClip> load_animation_clips(
    const std::filesystem::path& nif_path) {
    try {
        nif::File f = nif::load(nif_path.string());
        return detail::build_animations(f);
    } catch (const std::exception&) {
        return {};  // unreadable / unparseable NIF -> no clips
    }
}

}  // namespace assets
