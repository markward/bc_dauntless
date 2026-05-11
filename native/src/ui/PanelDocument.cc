// native/src/ui/PanelDocument.cc
#include "ui/PanelDocument.h"

#include <RmlUi/Core/Context.h>
#include <RmlUi/Core/ElementDocument.h>
#include <RmlUi/Core/Element.h>
#include <RmlUi/Core/EventListener.h>
#include <RmlUi/Core/Event.h>

#include <cstdlib>
#include <stdexcept>

namespace ui {

class PanelDocument::ClickListener : public Rml::EventListener {
public:
    explicit ClickListener(PanelDocument* owner) : owner_(owner) {}
    void ProcessEvent(Rml::Event& event) override {
        Rml::Element* target = event.GetCurrentElement();
        if (!target) return;
        // Each element we manage gets its integer id stamped onto its
        // "data-eid" attribute at append time; we look it back up here.
        Rml::String eid_str = target->GetAttribute<Rml::String>(
            "data-eid", Rml::String());
        if (eid_str.empty()) return;
        int eid = std::atoi(eid_str.c_str());
        auto it = owner_->click_cbs_.find(eid);
        if (it != owner_->click_cbs_.end()) {
            it->second();
        }
    }
private:
    PanelDocument* owner_;
};

PanelDocument::PanelDocument(Rml::Context* context,
                             const std::filesystem::path& rml_path,
                             const std::string& anchor,
                             float width_vw, float height_vh)
    : click_listener_(std::make_unique<ClickListener>(this))
{
    doc_ = context->LoadDocument(rml_path.string());
    if (!doc_) {
        throw std::runtime_error("PanelDocument: failed to load " + rml_path.string());
    }

    // In RmlUi, the <body> tag in the RML maps to the ElementDocument itself
    // (doc_), NOT to doc_->GetFirstChild(). Apply anchor + size as inline
    // properties directly on doc_ so the document occupies only the panel's
    // viewport region instead of stretching to fill the entire context.
    doc_->SetProperty("position", "absolute");
    doc_->SetProperty("width",  std::to_string(width_vw)  + "vw");
    doc_->SetProperty("height", std::to_string(height_vh) + "vh");
    // 30dp top offset is applied uniformly across all top-anchored UI so
    // panels and the HUD don't sit flush against the very top of the
    // viewport. Bottom-anchored panels are unaffected.
    if      (anchor == "top-left")     { doc_->SetProperty("left",  "0dp"); doc_->SetProperty("top",    "30dp"); }
    else if (anchor == "top-right")    { doc_->SetProperty("right", "0dp"); doc_->SetProperty("top",    "30dp"); }
    else if (anchor == "bottom-left")  { doc_->SetProperty("left",  "0dp"); doc_->SetProperty("bottom", "0dp"); }
    else if (anchor == "bottom-right") { doc_->SetProperty("right", "0dp"); doc_->SetProperty("bottom", "0dp"); }

    root_ = doc_->GetElementById("root");
    if (!root_) {
        throw std::runtime_error("PanelDocument: panel.rml missing #root element");
    }
    root_id_ = next_id_++;
    elements_[root_id_] = root_;
    root_->SetAttribute<Rml::String>("data-eid", std::to_string(root_id_));

    doc_->Show();
}

PanelDocument::~PanelDocument() {
    if (doc_) {
        doc_->Close();
    }
}

int PanelDocument::append_div(int parent_id, const std::string& class_names) {
    auto parent_it = elements_.find(parent_id);
    if (parent_it == elements_.end()) {
        throw std::runtime_error("PanelDocument::append_div: invalid parent id");
    }
    Rml::ElementPtr el_ptr = doc_->CreateElement("div");
    Rml::Element* el = el_ptr.get();
    int eid = next_id_++;
    el->SetAttribute<Rml::String>("data-eid", std::to_string(eid));
    if (!class_names.empty()) {
        el->SetClassNames(class_names.c_str());
    }
    parent_it->second->AppendChild(std::move(el_ptr));
    elements_[eid] = el;
    return eid;
}

void PanelDocument::recursive_drop_subtree(int element_id) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    Rml::Element* el = it->second;
    int n = el->GetNumChildren();
    for (int i = 0; i < n; ++i) {
        Rml::Element* child = el->GetChild(i);
        if (!child) continue;
        Rml::String eid_str = child->GetAttribute<Rml::String>(
            "data-eid", Rml::String());
        if (eid_str.empty()) continue;
        int child_eid = std::atoi(eid_str.c_str());
        recursive_drop_subtree(child_eid);
        elements_.erase(child_eid);
        click_cbs_.erase(child_eid);
    }
}

void PanelDocument::remove_element(int element_id) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    recursive_drop_subtree(element_id);
    Rml::Element* el = it->second;
    Rml::Element* parent = el->GetParentNode();
    if (parent) {
        parent->RemoveChild(el);  // discards returned ElementPtr → destroys
    }
    elements_.erase(it);
    click_cbs_.erase(element_id);
}

void PanelDocument::set_class(int element_id, const std::string& class_names) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    it->second->SetClassNames(class_names.c_str());
}

void PanelDocument::set_text(int element_id, const std::string& text) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    it->second->SetInnerRML(text.c_str());
}

void PanelDocument::set_visible(int element_id, bool visible) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    it->second->SetProperty("display", visible ? "block" : "none");
}

void PanelDocument::on_click(int element_id, std::function<void()> callback) {
    auto it = elements_.find(element_id);
    if (it == elements_.end()) return;
    Rml::Element* el = it->second;
    if (callback) {
        click_cbs_[element_id] = std::move(callback);
        el->AddEventListener("click", click_listener_.get());
    } else {
        click_cbs_.erase(element_id);
        el->RemoveEventListener("click", click_listener_.get());
    }
}

void PanelDocument::set_css_var(const std::string& name, const std::string& value) {
    if (!doc_) return;
    doc_->SetProperty(name.c_str(), value.c_str());
}

void PanelDocument::clear() {
    if (!root_) return;
    while (root_->GetNumChildren() > 0) {
        Rml::Element* child = root_->GetChild(0);
        if (!child) break;
        Rml::String eid_str = child->GetAttribute<Rml::String>(
            "data-eid", Rml::String());
        int child_eid = eid_str.empty() ? 0 : std::atoi(eid_str.c_str());
        if (child_eid != 0) {
            recursive_drop_subtree(child_eid);
            elements_.erase(child_eid);
            click_cbs_.erase(child_eid);
        }
        root_->RemoveChild(child);
    }
}

}  // namespace ui
