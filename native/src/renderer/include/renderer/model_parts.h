// native/src/renderer/include/renderer/model_parts.h
#pragma once

#include <string>
#include <vector>

#include <glm/glm.hpp>

namespace assets { struct Model; }

namespace renderer {

/// One node of a model, with its rest-pose bounds, for the SPV's part list.
struct ModelPart {
    std::string name;
    std::string parent;          ///< empty for the root
    bool        candidate = false;
    glm::vec3   bounds_min{0.0f};
    glm::vec3   bounds_max{0.0f};
    bool        has_bounds = false;
};

/// Every named node of `model`, rest pose, MODEL units.
///
/// `candidate` marks the nodes a human would call a "part". Those are the
/// children of the node named "Scene Root" -- measured on the real
/// BirdOfPrey.nif with native/tools/dump_nif_tree, whose Scene Root has
/// exactly four children: head, left wing, left wing01, birdofprey. Scene Root
/// itself sits below two UNNAMED wrapper nodes, so this cannot simply use
/// model.root_node. Hulls with no "Scene Root" fall back to the first node
/// with more than one child.
///
/// The NIF's own "Top Level Object" label is NOT usable for this: it is a
/// stream-framing marker that precedes a block's real type name
/// (native/src/nif/src/file.cc:81-91), it is discarded during parse, and
/// assets::Node has no field for it.
///
/// `bounds_*` cover the node's WHOLE SUBTREE, because a part node carries no
/// meshes of its own -- they hang off an interposed __NDL_MultiMtl_Node child
/// (a 3ds Max exporter artifact). Bounds taken from a node's own meshes would
/// be empty for every part on every real hull.
std::vector<ModelPart> model_parts(const assets::Model& model);

}  // namespace renderer
