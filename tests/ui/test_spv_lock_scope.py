"""The pose-preview lock (spec 7.7) greys the Functional list only; the tab
strip and the Physical body must stay interactive."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
CSS = re.sub(r"/\*.*?\*/", "", (ROOT / "css" / "ship_property_viewer.css").read_text(encoding="utf-8"), flags=re.S)
JS = (ROOT / "js" / "ship_property_viewer.js").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def _lock_selectors():
    return [m.group(1).strip() for m in
            re.finditer(r"([^{}]*spv-syslist--locked[^{}]*)\{", CSS)]


def test_lock_class_is_applied_to_functional_body_only():
    m = re.search(r"getElementById\('([^']+)'\);\s*if \(\w+\) \w+\.classList"
                  r"\.toggle\('spv-syslist--locked'", JS)
    assert m and m.group(1) == "spv-syslist-body"


def test_css_lock_targets_functional_body():
    sels = _lock_selectors()
    assert sels and all(s == "#spv-syslist-body.spv-syslist--locked"
                        for s in sels), sels


def test_tabs_and_physical_body_are_not_inside_the_locked_element():
    body = re.search(r'<div id="spv-syslist-body"[^>]*>(.*?)</div>', HTML, re.S)
    inner = body.group(1)
    assert "spv-systabs" not in inner and "spv-physical-body" not in inner
    assert 'id="spv-systabs"' in HTML and 'id="spv-physical-body"' in HTML
