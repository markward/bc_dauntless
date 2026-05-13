// native/src/ui/include/ui/PanelDocument.h
#pragma once

#include <filesystem>
#include <functional>
#include <memory>
#include <string>
#include <unordered_map>

namespace Rml {
    class Context;
    class ElementDocument;
    class Element;
}

namespace ui {

/// One PanelDocument owns one Rml::ElementDocument loaded from panel.rml.
/// Python composes the body dynamically via the binding primitives below;
/// the PanelDocument tracks element handles by integer id so binding calls
/// don't need to leak Rml::Element pointers into Python.
class PanelDocument {
public:
    PanelDocument(Rml::Context* context,
                  const std::filesystem::path& rml_path,
                  const std::string& anchor,
                  float width_vw, float height_vh);
    ~PanelDocument();

    PanelDocument(const PanelDocument&) = delete;
    PanelDocument& operator=(const PanelDocument&) = delete;

    /// The opaque id of the document's root element (the <div id="root">).
    int root_element_id() const { return root_id_; }

    /// Returns true if this panel owns the given element id.
    bool has_element(int element_id) const {
        return elements_.find(element_id) != elements_.end();
    }

    /// Element-tree mutation primitives. Each returns / accepts integer
    /// element ids that are unique within this PanelDocument.
    int  append_div(int parent_id, const std::string& class_names);
    void remove_element(int element_id);
    void set_class(int element_id, const std::string& class_names);
    void set_text(int element_id, const std::string& text);
    void set_visible(int element_id, bool visible);

    /// Register a click callback for an element. Pass nullptr to clear.
    /// The callback is invoked synchronously when the element receives a
    /// "click" event (RmlUi raises this on left-mouse-button-up).
    void on_click(int element_id, std::function<void()> callback);

    /// Set a CSS custom property on the document root (applies to all
    /// descendants via `var()` references in components.rcss).
    void set_css_var(const std::string& name, const std::string& value);

    /// Clear all body children. The root element itself stays.
    void clear();

    /// Toggle whole-document visibility. When hidden, the document is
    /// removed from layout and does NOT receive pointer events — clicks
    /// pass through to whatever's behind it.
    void set_visible(bool visible);

    /// Write the panel document's screen-pixel rect to the out params.
    /// (x, y) is the top-left corner; (w, h) is the panel's outer size.
    /// Returns false if the panel isn't loaded yet (writes zeros).
    bool bounds(float* out_x, float* out_y,
                float* out_w, float* out_h) const noexcept;

private:
    Rml::ElementDocument* doc_       = nullptr;
    Rml::Element*         root_       = nullptr;
    int                   root_id_    = 0;

    /// Constructor-set anchor; replayed by set_visible(true) so a
    /// re-shown panel returns to its original anchor instead of having
    /// the offscreen-hide overrides linger.
    std::string           anchor_;

    /// Element-id counter shared across every PanelDocument. Per-panel
    /// counters would collide because the binding layer resolves element
    /// ids by "first panel that owns this id wins" (host_bindings.cc).
    /// Two panels each numbering their #root as 1 routes the second
    /// panel's appends into the first panel's tree.
    static int            s_next_id_;
    std::unordered_map<int, Rml::Element*>            elements_;
    std::unordered_map<int, std::function<void()>>    click_cbs_;

    class ClickListener;  // forward decl; defined in .cc
    std::unique_ptr<ClickListener> click_listener_;

    /// Apply the inline anchor properties (left/right/top/bottom and any
    /// transform) for ``anchor_`` to the document. Used by the constructor
    /// AND by set_visible(true) to clear the offscreen-hide overrides.
    void apply_anchor();

    void recursive_drop_subtree(int element_id);
};

}  // namespace ui
