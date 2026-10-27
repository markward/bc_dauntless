"""Static guard for the boot notice page (no headless CEF render exists).

Asserts index.html loads it, the page defines setBootNotice, answers the
arm payload with the one event BootNoticePanel accepts, and offers no way to
dismiss the notice."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"
JS = (ROOT / "js" / "boot_notice.js").read_text(encoding="utf-8")
CSS = (ROOT / "css" / "boot_notice.css").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_index_loads_the_page():
    assert 'src="js/boot_notice.js"' in HTML
    assert 'href="css/boot_notice.css"' in HTML
    assert 'id="boot-notice"' in HTML


def test_defines_the_entry_point():
    assert "function setBootNotice(payload)" in JS


def test_only_emits_the_acknowledgement():
    assert re.findall(r"dauntlessEvent\('([^']+)'\)", JS) == ["boot-notice/shown"]


def test_nothing_on_the_notice_is_clickable():
    section = HTML[HTML.index('<section id="boot-notice">'):]
    section = section[:section.index("</section>")]
    assert "onclick" not in section and "<button" not in section


def test_white_antonio_on_black():
    assert 'font-family: "Antonio"' in CSS
    assert "background: #000;" in CSS
    assert "color: #fff;" in CSS
