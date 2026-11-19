"""Account icons, last played, search, drag to reorder, close-to-tray choice."""
import json

import pytest

from switcher import icons
from switcher.store import Store
from switcher.ui import played_text


def test_new_profile_fields_default_and_survive_save(tmp_path):
    store = Store(tmp_path)
    pid = store.add("Main")
    p = store.get(pid)
    assert (p["icon"], p["color"], p["last_played"]) == ("letter", "", 0)
    store.update(pid, icon="glyph:bolt", color="#4d8dff")
    store.set_active(pid)
    p = store.get(pid)
    assert p["icon"] == "glyph:bolt" and p["color"] == "#4d8dff" and p["last_played"] > 0


def test_bad_icon_and_color_values_are_ignored(tmp_path):
    store = Store(tmp_path)
    pid = store.add("Main")
    raw = json.loads(store.path.read_text())
    raw["profiles"][0].update(icon="../../evil", color="red; drop", last_played="soon")
    store.path.write_text(json.dumps(raw))
    p = store.get(pid)
    assert (p["icon"], p["color"], p["last_played"]) == ("letter", "", 0)


def test_old_files_without_new_fields_still_load(tmp_path):
    store = Store(tmp_path)
    store.path.write_text(json.dumps({"version": 3, "active": None, "settings": {},
                                      "profiles": [{"id": "11111111-1111-4111-8111-111111111111", "label": "Old"}]}))
    data = store.read()
    assert data["profiles"][0]["icon"] == "letter" and data["settings"]["close_action"] == "ask"


def test_reorder_never_loses_an_account(tmp_path):
    store = Store(tmp_path)
    a, b, c = store.add("A"), store.add("B"), store.add("C")
    store.reorder([c, a, "not-an-id"])
    assert [p["label"] for p in store.read()["profiles"]] == ["C", "A", "B"]


def test_close_action_setting(tmp_path):
    store = Store(tmp_path)
    store.set_close_action("tray")
    assert store.read()["settings"]["close_action"] == "tray"
    store.set_close_action("nonsense")
    assert store.read()["settings"]["close_action"] == "ask"


@pytest.mark.parametrize("ago, text", [(0, ""), (5, "Played just now"), (120, "Played 2 min ago"),
                                       (3600, "Played 1 hour ago"), (3 * 3600, "Played 3 hours ago"),
                                       (86400, "Played 1 day ago"), (2 * 86400, "Played 2 days ago")])
def test_played_text(ago, text):
    now = 2_000_000_000
    assert played_text(now - ago if ago else 0, now=now) == text


def test_played_text_older_than_a_week_shows_the_date():
    assert played_text(1_000_000_000, now=1_000_000_000 + 30 * 86400).startswith("Played ")


def test_every_emblem_draws_something():
    for name in icons.GLYPHS:
        im = icons.glyph_image(name, 40, "#ff4655")
        assert im.size == (40, 40) and im.getchannel("A").getbbox() is not None, name


def test_picture_upload_is_cropped_saved_and_removed(tmp_path):
    from PIL import Image
    src = tmp_path / "me.jpg"
    Image.new("RGB", (400, 200), "#123456").save(src)
    pid = Store(tmp_path).add("Main")
    dest = icons.import_picture(src, tmp_path, pid)
    with Image.open(dest) as im:
        assert im.size == (icons.STORED_SIZE, icons.STORED_SIZE)
    assert icons.load_picture(tmp_path, pid, 46).size == (46, 46)
    icons.remove_picture(tmp_path, pid)
    assert not dest.exists()


def test_non_pictures_are_refused(tmp_path):
    from switcher.errors import UserError
    fake = tmp_path / "virus.png"
    fake.write_bytes(b"MZ not really a png")
    with pytest.raises(UserError):
        icons.read_picture(fake)


def test_picture_path_rejects_bad_ids(tmp_path):
    from switcher.errors import UserError
    with pytest.raises(UserError):
        icons.custom_path(tmp_path, "../../x")
