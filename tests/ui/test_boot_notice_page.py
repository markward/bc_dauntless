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
    section = _section()
    assert "onclick" not in section and "<button" not in section


def _section():
    section = HTML[HTML.index('<section id="boot-notice">'):]
    return section[:section.index("</section>")]


def test_white_antonio_on_black():
    assert 'font-family: "Antonio Variable", "Antonio"' in CSS
    assert "background: #000;" in CSS
    assert "color: #fff;" in CSS


def test_the_title_lockup_reads_bridge_commander_dauntless():
    section = _section()
    spread = section[section.index('class="bn-spread"'):]
    spread = spread[:spread.index("</div>")]
    letters = re.findall(r"<span>([A-Z])</span>", spread)
    assert "".join(letters) == "BRIDGECOMMANDER"
    assert 'class="bn-gap"' in spread
    assert re.search(r'class="bn-wordmark">DAUNTLESS<', section)


def test_the_wordmark_gets_the_real_bold_not_a_synthesised_one():
    """The bundled Antonio is the variable build; a face declared for normal
    weight only (global.css) makes the browser fake the bold."""
    face = CSS[CSS.index("@font-face"):]
    face = face[:face.index("}")]
    assert 'font-family: "Antonio Variable"' in face
    assert "font-weight: 100 700;" in face
    assert "font-weight: 700;" in CSS
