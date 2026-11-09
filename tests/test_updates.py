import io
import json
import urllib.error

from switcher import updates
from switcher.updates import Result, Settings, check, is_newer, parse_version, safe_url


def fake_opener(payload=None, error=None):
    def opener(request, timeout=0):
        if error:
            raise error
        return io.BytesIO(json.dumps(payload).encode())
    return opener


def test_parse_and_compare():
    assert parse_version("v3.7.0") == (3, 7, 0)
    assert parse_version("garbage") == ()
    assert is_newer("v3.7.0", "3.6.3")
    assert is_newer("3.10.0", "3.9.9")
    assert not is_newer("3.6.3", "3.6.3")
    assert not is_newer("3.6", "3.6.0")
    assert not is_newer("oops", "3.6.3")


def test_newer_release_found():
    r = check(fake_opener({"tag_name": "v9.0.0", "html_url": updates.PAGE_PREFIX + "releases/tag/v9.0.0"}), "3.6.3")
    assert r == Result("newer", "9.0.0", updates.PAGE_PREFIX + "releases/tag/v9.0.0")


def test_same_version_is_current():
    assert check(fake_opener({"tag_name": "v3.6.3"}), "3.6.3").status == "current"


def test_prerelease_and_draft_ignored():
    assert check(fake_opener({"tag_name": "v9.0.0", "prerelease": True}), "3.6.3").status == "current"
    assert check(fake_opener({"tag_name": "v9.0.0", "draft": True}), "3.6.3").status == "current"


def test_failures_are_unavailable():
    assert check(fake_opener(error=urllib.error.HTTPError("u", 404, "nf", {}, None))).status == "unavailable"
    assert check(fake_opener(error=OSError("offline"))).status == "unavailable"
    assert check(fake_opener(payload={"nope": 1})).status == "unavailable"


def test_link_is_always_this_projects_page():
    assert safe_url("https://evil.example/x") == updates.RELEASES_URL
    assert safe_url(None) == updates.RELEASES_URL
    assert safe_url(updates.PAGE_PREFIX + "releases/tag/v1") .startswith(updates.PAGE_PREFIX)


def test_settings_roundtrip_and_schedule(tmp_path):
    s = Settings(tmp_path)
    assert s.read() == {"auto": True, "last_check": 0.0} and s.due(now=1e9)
    s.write(last_check=1000.0)
    assert not s.due(now=1000.0 + 3600) and s.due(now=1000.0 + updates.CHECK_EVERY)
    s.write(auto=False)
    assert not s.due(now=1e12)
    (tmp_path / "update.json").write_text("{broken")
    assert s.read()["auto"] is True
