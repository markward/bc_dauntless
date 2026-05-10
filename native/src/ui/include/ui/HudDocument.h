// native/src/ui/include/ui/HudDocument.h
#pragma once

#include "UiSystem.h"  // for HudState

#include <filesystem>

namespace Rml {
    class Context;
    class ElementDocument;
    class Element;
}

namespace ui {

class HudDocument {
public:
    HudDocument() = default;
    /// Load rml_path into context and cache the four text element pointers.
    HudDocument(Rml::Context* context, const std::filesystem::path& rml_path);

    HudDocument(const HudDocument&) = delete;
    HudDocument& operator=(const HudDocument&) = delete;

    /// Push new values into the HUD element text. No-op if document failed to load.
    void update(const HudState& state);

private:
    Rml::ElementDocument* doc_       = nullptr;
    Rml::Element*         el_ship_   = nullptr;
    Rml::Element*         el_system_ = nullptr;
    Rml::Element*         el_pos_    = nullptr;
    Rml::Element*         el_rot_    = nullptr;
};

}  // namespace ui
