"""(lazarus) The game in Steam's library as a non-Steam game (builder/linux/steam_shortcut.py), for Gaming Mode.

shortcuts.vdf is Steam's binary VDF: the other games in it come back as they were, ours is added once and brought up to
date after that, never twice, and nothing is written while Steam runs (it would write its own copy back over it).

python -I -B tests/test_steam_shortcut.py
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "builder" / "linux"))
import steam_shortcut  # noqa: E402


class SteamShortcutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="steam-shortcut-")
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.vdf = self.home / ".local/share/Steam/userdata/12345/config/shortcuts.vdf"
        self.vdf.parent.mkdir(parents=True)
        self.game = base / "game"
        (self.game / "bin").mkdir(parents=True)
        (self.game / "image.bin").write_bytes(b"")
        exe = self.game / "bin" / "hookshot"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, running=False):
        return steam_shortcut.add(str(self.game), home=str(self.home), running=lambda: running)

    def entries(self):
        return steam_shortcut.loads(self.vdf.read_bytes())["shortcuts"]

    def test_round_trip(self):
        root = {"shortcuts": {"0": {"appid": -5, "AppName": "Other", "Exe": '"/x"', "tags": {"0": "fav"}}}}
        self.assertEqual(steam_shortcut.loads(steam_shortcut.dumps(root)), root)

    def test_added_once_beside_the_others(self):
        self.vdf.write_bytes(steam_shortcut.dumps({"shortcuts": {"0": {"AppName": "Other", "Exe": '"/x"', "tags": {}}}}))
        self.assertTrue(self.add()[0])
        self.assertTrue(self.add()[0])
        names = [e["AppName"] for e in self.entries().values()]
        self.assertEqual(names, ["Other", steam_shortcut.NAME])
        ours = self.entries()["1"]
        script = self.game / steam_shortcut.SCRIPT
        self.assertEqual(ours["Exe"], '"%s"' % script)
        self.assertEqual(ours["appid"], steam_shortcut.app_id(ours["Exe"], steam_shortcut.NAME))
        self.assertLess(ours["appid"], 0)   # (the top bit set, signed as Steam writes it)
        text = script.read_text()
        self.assertTrue(os.access(script, os.X_OK))
        self.assertIn('HOS_FULLSCREEN="${HOS_FULLSCREEN:-1}"', text)
        self.assertIn("exec ./bin/hookshot", text)

    def test_nothing_written_while_steam_runs(self):
        ok, message = self.add(running=True)
        self.assertFalse(ok)
        self.assertIn("Steam is running", message)
        self.assertFalse(self.vdf.exists())

    def test_no_game_no_entry(self):
        (self.game / "image.bin").unlink()
        self.assertFalse(self.add()[0])
        self.assertFalse(self.vdf.exists())


if __name__ == "__main__":
    unittest.main()
