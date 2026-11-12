"""(lazarus) The game as a non-Steam game in Steam's library, so it starts from Gaming Mode (SteamOS, Legion Go S, Steam Deck).

Steam keeps its non-Steam games in userdata/<account>/config/shortcuts.vdf, a binary VDF file, one per account that has
signed in on this PC. Each gets an entry (or has its entry brought up to date: the one whose Exe is ours) that starts
the game folder's steam-play script: the game itself, fullscreen, with no launcher window in between, which Gaming Mode
could not drive with the pad. Started by Steam, the game gets Steam Input's pad, the handheld's own controls as the
player's Steam layout maps them (host/pad_sdl.c, host/steam_pads.h).

Steam reads the file when it starts and writes its own copy back, so it is written with Steam closed: add() says when
Steam is running and leaves the file alone, and close_steam() asks it to quit (steam -shutdown). On SteamOS, going back
to Gaming Mode starts Steam again, with the game in the library.

    python3 steam_shortcut.py <game folder>     adds it (Steam closed), says what it did
"""
import binascii
import os
import shutil
import stat
import subprocess
import sys
import time

NAME = "Lazarus"
SCRIPT = "steam-play"
TAGS = ("Lazarus",)

# (the script Steam starts: the game from its folder, as hookshot-launch starts it, without the AppImage's or Steam's
# library path, so it loads its own SDL; fullscreen unless HOS_FULLSCREEN is set in the shortcut's launch options)
STEAM_PLAY = """#!/bin/sh
# (lazarus) Started by Steam (a non-Steam game, builder/linux/steam_shortcut.py): the game itself, fullscreen.
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"
unset LD_LIBRARY_PATH
export HOOKSHOT_NO_UPDATE_CHECK=1
export HOS_FULLSCREEN="${HOS_FULLSCREEN:-1}"
if [ -x ./bin/hookshot ]; then
    exec ./bin/hookshot "$@"
fi
exec ./hookshot "$@"
"""


# --- binary VDF: 0x00 a map, 0x01 a string, 0x02 a 32-bit integer, 0x08 the end of a map; names and strings end in 0x00
class VdfError(ValueError):
    pass


def _cstr(data, at):
    end = data.find(b"\0", at)
    if end < 0:
        raise VdfError("a name or string has no end")
    return data[at:end].decode("utf-8", "replace"), end + 1


def _map(data, at):
    out = {}
    while True:
        if at >= len(data):
            raise VdfError("a map has no end")
        kind = data[at]
        at += 1
        if kind == 0x08:
            return out, at
        key, at = _cstr(data, at)
        if kind == 0x00:
            out[key], at = _map(data, at)
        elif kind == 0x01:
            out[key], at = _cstr(data, at)
        elif kind == 0x02:
            if at + 4 > len(data):
                raise VdfError("an integer is cut short")
            out[key] = int.from_bytes(data[at:at + 4], "little", signed=True)
            at += 4
        elif kind == 0x07:   # (a 64-bit integer: kept as bytes)
            out[key] = ("u64", data[at:at + 8])
            at += 8
        else:
            raise VdfError("unknown field type %#x" % kind)


def loads(data):
    if not data:
        return {"shortcuts": {}}
    out, at = _map(data, 0)
    return out


def _dump_map(m):
    b = bytearray()
    for key, value in m.items():
        k = str(key).encode("utf-8") + b"\0"
        if isinstance(value, dict):
            b += b"\x00" + k + _dump_map(value)
        elif isinstance(value, tuple) and value and value[0] == "u64":
            b += b"\x07" + k + value[1]
        elif isinstance(value, int):
            b += b"\x02" + k + (value & 0xFFFFFFFF).to_bytes(4, "little")
        else:
            b += b"\x01" + k + str(value).encode("utf-8") + b"\0"
    return bytes(b + b"\x08")


def dumps(root):
    return _dump_map(root) + b"\x08"


# --- Steam's places
def steam_roots(home=None):
    home = home or os.path.expanduser("~")
    seen, out = set(), []
    for p in (".local/share/Steam", ".steam/steam", ".steam/root",
              ".var/app/com.valvesoftware.Steam/.local/share/Steam", ".var/app/com.valvesoftware.Steam/data/Steam"):
        path = os.path.join(home, p)
        if os.path.isdir(os.path.join(path, "userdata")):
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                out.append(path)
    return out


def shortcut_files(home=None):
    """userdata/<account>/config/shortcuts.vdf of every account that signed in (the file may not be there yet)"""
    out = []
    for root in steam_roots(home):
        users = os.path.join(root, "userdata")
        for account in sorted(os.listdir(users)):
            if account.isdigit() and account != "0" and os.path.isdir(os.path.join(users, account)):
                out.append(os.path.join(users, account, "config", "shortcuts.vdf"))
    return out


def steam_running(run=subprocess.run):
    try:
        return run(["pgrep", "-x", "steam"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def close_steam(wait=30.0, run=subprocess.run, popen=subprocess.Popen, clock=time.monotonic, sleep=time.sleep):
    """asks Steam to quit and waits for it: True once it is gone"""
    if not steam_running(run):
        return True
    steam = shutil.which("steam")
    if not steam:
        return False
    try:
        popen([steam, "-shutdown"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    end = clock() + wait
    while clock() < end:
        sleep(0.5)
        if not steam_running(run):
            sleep(1.0)   # (its last writes)
            return True
    return False


def app_id(exe, name):
    """the id Steam gives a non-Steam game: the CRC-32 of its quoted Exe and its name, top bit set (signed in the file)"""
    crc = binascii.crc32((exe + name).encode("utf-8")) & 0xFFFFFFFF
    v = crc | 0x80000000
    return v - (1 << 32)


def write_script(folder):
    path = os.path.join(folder, SCRIPT)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(STEAM_PLAY)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def entry(folder, script, icon, old=None):
    exe = '"%s"' % script
    e = dict(old or {})
    e.update({
        "appid": app_id(exe, NAME),
        "AppName": NAME,
        "Exe": exe,
        "StartDir": '"%s"' % folder,
        "icon": icon if icon and os.path.exists(icon) else "",
        "ShortcutPath": "",
        "IsHidden": 0,
        "AllowDesktopConfig": 1,
        "AllowOverlay": 1,
        "OpenVR": 0,
        "Devkit": 0,
        "DevkitGameID": "",
        "DevkitOverrideAppID": 0,
        "FlatpakAppID": "",
    })
    e.setdefault("LaunchOptions", "")
    e.setdefault("LastPlayTime", 0)
    e["tags"] = {str(i): t for i, t in enumerate(TAGS)}
    return e


def add_to_file(path, folder, script, icon):
    """our entry in one shortcuts.vdf (added, or the old one brought up to date): "added" or "updated" """
    data = b""
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
    root = loads(data)
    shortcuts = root.setdefault("shortcuts", {})
    if not isinstance(shortcuts, dict):
        raise VdfError("shortcuts is not a map")
    exe = '"%s"' % script
    key = next((k for k, v in shortcuts.items() if isinstance(v, dict) and v.get("Exe") == exe), None)
    what = "updated" if key is not None else "added"
    if key is None:
        key = str(max([int(k) for k in shortcuts if str(k).isdigit()] + [-1]) + 1)
    shortcuts[key] = entry(folder, script, icon, shortcuts.get(key))
    root["shortcuts"] = {str(i): v for i, v in enumerate(shortcuts[k] for k in sorted(shortcuts, key=lambda k: int(k) if str(k).isdigit() else 1 << 30))}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        shutil.copyfile(path, path + ".lazarus-backup")   # (the file as it was, once per write)
    tmp = path + ".lazarus-tmp"
    with open(tmp, "wb") as f:
        f.write(dumps(root))
    os.replace(tmp, path)
    return what


def add(folder, home=None, running=steam_running):
    """the game in every Steam account's library. Returns (ok, message in the player's words)"""
    folder = os.path.abspath(os.path.expanduser(folder))
    if not (os.path.isfile(os.path.join(folder, "image.bin")) and
            (os.access(os.path.join(folder, "bin", "hookshot"), os.X_OK) or os.path.isfile(os.path.join(folder, "hookshot")))):
        return False, "No built game in %s: build it first." % folder
    if any(ch in folder for ch in '"\r\n\0'):
        return False, "The game folder's name has a quote or a line break, which Steam's library entry cannot hold."
    files = shortcut_files(home)
    if not files:
        return False, "Steam was not found (no account has signed in on this PC). Sign in to Steam once, then try again."
    if running():
        return False, "Steam is running: close it first (or let the builder close it), so it does not write over the entry."
    script = write_script(folder)
    icon = os.path.join(folder, "hookshot.png")
    done = []
    for path in files:
        try:
            done.append(add_to_file(path, folder, script, icon))
        except (OSError, VdfError) as e:
            return False, "Steam's library file %s could not be changed: %s" % (path, e)
    return True, ("%s is in Steam's library as a non-Steam game (%d account%s). Go back to Gaming Mode (or start Steam): "
                  "it is under Non-Steam, and starts fullscreen with the handheld's controls." %
                  (NAME, len(files), "" if len(files) == 1 else "s"))


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[-1].strip())
        return 2
    ok, message = add(argv[1])
    if not ok and "Steam is running" in message and close_steam():
        ok, message = add(argv[1])
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
