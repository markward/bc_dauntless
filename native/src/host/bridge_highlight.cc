// native/src/host/bridge_highlight.cc
#include "bridge_highlight.h"
#include "developer_mode.h"

#include <renderer/bridge_pass.h>

namespace dauntless {

bool apply_bridge_highlight(BridgeHighlight& state, renderer::BridgePass* pass,
                            unsigned long long model_handle, int selected,
                            int hover) {
    if (!is_developer_mode()) return false;
    state = model_handle == 0 ? BridgeHighlight{}
                              : BridgeHighlight{model_handle, selected, hover};
    if (pass != nullptr)
        pass->set_highlight(state.model, state.selected, state.hover);
    return true;
}

}  // namespace dauntless
