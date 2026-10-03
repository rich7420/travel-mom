from html.parser import HTMLParser
import re

from fastapi.testclient import TestClient

from app.main import app
from scripts import build_user_guide as guide


class GuideHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.fragments = []
        self.visible_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        assert "style" not in attrs
        assert not any(name.startswith("on") for name in attrs)
        if tag == "script":
            assert attrs.get("src", "").startswith("/static/")
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.fragments.append(attrs["href"][1:])
        if attrs.get("target") == "_blank":
            assert "noopener" in attrs.get("rel", "").split()

    def handle_data(self, data):
        self.visible_text.append(data)


def test_generated_guide_matches_manual_and_has_resolved_safe_navigation():
    output = guide.OUTPUT.read_text(encoding="utf-8")
    assert output == guide.render_guide(), "Run python scripts/build_user_guide.py"
    assert "127.0.0.1" not in output and "localhost" not in output
    parsed = GuideHTML()
    parsed.feed(output)
    assert len(set(parsed.ids)) == len(parsed.ids)
    assert set(parsed.fragments) <= set(parsed.ids)
    assert set(guide.CHAPTER_IDS.values()) <= set(parsed.ids)
    assert not re.search(r"v\d+\.\d+", "".join(parsed.visible_text))
    for fragment in re.findall(r'/static/guide\.html#([a-z-]+)', (guide.ROOT / 'app/mom_static/index.html').read_text()):
        assert fragment in parsed.ids
    app_js = (guide.ROOT / 'app/mom_static/app.js').read_text()
    for fragment in re.findall(r",(?:true|!keepScroll),'([a-z-]+)'\);", app_js):
        assert fragment in parsed.ids


def test_check_detects_drift_without_writing(monkeypatch, tmp_path):
    output = tmp_path / "guide.html"
    output.write_bytes(guide.render_guide().encode("utf-8"))
    monkeypatch.setattr(guide, "OUTPUT", output)
    monkeypatch.setattr('sys.argv', ['build_user_guide.py', '--check'])
    before = output.stat().st_mtime_ns
    assert guide.main() == 0
    assert output.stat().st_mtime_ns == before
    output.write_bytes(b"stale guide")
    before = output.stat().st_mtime_ns
    assert guide.main() == 1
    assert output.read_bytes() == b"stale guide"
    assert output.stat().st_mtime_ns == before


def test_guide_assets_are_readable_in_local_mode_with_strict_csp():
    with TestClient(app) as client:
        for asset in ['guide.html', 'guide.css', 'guide.js']:
            response = client.get(f'/static/{asset}')
            assert response.status_code == 200
            assert "'unsafe-inline'" not in response.headers['content-security-policy']
