// native/src/ui/HudDocument.cc
#include "ui/HudDocument.h"

#include <RmlUi/Core/Context.h>
#include <RmlUi/Core/ElementDocument.h>
#include <RmlUi/Core/Element.h>

#include <cstdio>

namespace ui {

HudDocument::HudDocument(Rml::Context* context,
                         const std::filesystem::path& rml_path) {
    doc_ = context->LoadDocument(rml_path.string());
    if (!doc_) return;
    doc_->Show();

    el_ship_   = doc_->GetElementById("ship-name");
    el_system_ = doc_->GetElementById("system-name");
    el_pos_    = doc_->GetElementById("pos");
    el_rot_    = doc_->GetElementById("rot");
}

void HudDocument::update(const HudState& state) {
    if (!doc_) return;

    char buf[256];

    if (el_ship_)
        el_ship_->SetInnerRML(state.ship_name.c_str());

    if (el_system_)
        el_system_->SetInnerRML(state.system_name.c_str());

    if (el_pos_) {
        std::snprintf(buf, sizeof(buf), "%.1f %.1f %.1f",
                      state.pos_x, state.pos_y, state.pos_z);
        el_pos_->SetInnerRML(buf);
    }

    if (el_rot_) {
        // \xc2\xb0 is the UTF-8 encoding of the degree sign (U+00B0).
        std::snprintf(buf, sizeof(buf),
                      "Y%.0f\xc2\xb0 P%.0f\xc2\xb0 R%.0f\xc2\xb0",
                      state.yaw_deg, state.pitch_deg, state.roll_deg);
        el_rot_->SetInnerRML(buf);
    }
}

}  // namespace ui
