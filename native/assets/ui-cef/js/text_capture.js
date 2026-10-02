// text_capture.js -- keyboard capture for in-game CEF text fields.
//
// Reports focus/blur of editable elements so the host can hand the keyboard
// to the page (engine/ui/text_capture.py -> native KeyGate), and gives every
// field the same three keys: Esc reverts then blurs, Enter blurs (the DOM
// `change` event is the commit), Tab stays in the page. Kept thin on purpose:
// all other logic lives in Python where it is tested.
//
// A panel hosting a field puts data-panel="<registry name>" on its root.
// Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S3
(function () {
    var TEXT_TYPES = ['text', 'search', 'number', 'email', 'url', 'password', 'tel'];
    var saved = new WeakMap();   // element -> value at focus

    function isEditable(el) {
        if (!el || el.nodeType !== 1) return false;
        if (el.tagName === 'TEXTAREA') return true;
        if (el.tagName === 'INPUT') {
            return TEXT_TYPES.indexOf((el.getAttribute('type') || 'text').toLowerCase()) >= 0;
        }
        return el.isContentEditable === true;
    }

    function isField(el) { return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'; }
    function valueOf(el) { return isField(el) ? el.value : el.textContent; }
    function setValue(el, v) { if (isField(el)) el.value = v; else el.textContent = v; }

    function ownerOf(el) {
        var root = el.closest('[data-panel]');
        return root ? root.getAttribute('data-panel') : '';
    }

    // Restore BEFORE blurring, so no `change` fires and nothing commits.
    function revertAndBlur(el) {
        if (saved.has(el)) setValue(el, saved.get(el));
        el.blur();
    }

    document.addEventListener('focusin', function (e) {
        var el = e.target;
        if (!isEditable(el)) return;
        saved.set(el, valueOf(el));
        dauntlessEvent('kbd/focus:' + ownerOf(el));
    }, true);

    document.addEventListener('focusout', function (e) {
        if (!isEditable(e.target)) return;
        // Field -> field (Tab): the next focusin re-reports; keep capture.
        if (isEditable(e.relatedTarget)) return;
        dauntlessEvent('kbd/blur');
    }, true);

    document.addEventListener('keydown', function (e) {
        var el = e.target;
        if (!isEditable(el)) return;
        if (e.key === 'Escape') {
            e.preventDefault();
            e.stopPropagation();
            revertAndBlur(el);
        } else if (e.key === 'Enter' && el.tagName !== 'TEXTAREA') {
            e.preventDefault();
            el.blur();
        }
    }, true);

    // Host-forced release (panel closed, mission swap, click on the game
    // world): abandon the edit.
    window.__dauntlessBlurText = function () {
        var el = document.activeElement;
        if (isEditable(el)) revertAndBlur(el);
    };
    // For in-panel cancel/commit buttons.
    window.__dauntlessTextCancel = function (el) {
        if (isEditable(el)) revertAndBlur(el);
    };
    window.__dauntlessTextCommit = function (el) {
        if (el) el.blur();
    };
})();
