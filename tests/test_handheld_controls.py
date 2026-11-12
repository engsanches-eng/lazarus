"""(lazarus) The built-in controls of a Windows handheld reach the game (Legion Go S).

Three things left such a handheld with no controls, though the game ran:
- the launcher stayed in front: the game counts pads only with its own window in front, and with no mouse there was
  nothing to click it with. The builder's --play passes on the right to come to the front, and the window asks for it;
- with the desktop or the taskbar in front no other program has the input, so the game keeps it, as for an overlay;
- SDL opened a pad it never heard from (a second interface of the built-in controls), and any open SDL pad kept XInput,
  which reads those controls, from being read. Now only a pad that has given input does.

python -I -B tests/test_handheld_controls.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def block(text, marker):
    start = text.index(marker)
    end = text.index("{", start) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def check(ok, message):
    if not ok:
        raise SystemExit("FAIL: " + message)


def main():
    hid = (ROOT / "host" / "nn_hid.c").read_text(encoding="utf-8")
    sdl = (ROOT / "host" / "pad_sdl.c").read_text(encoding="utf-8")
    display = (ROOT / "host" / "display.c").read_text(encoding="utf-8")
    setup = (ROOT / "builder" / "setup" / "setup.c").read_text(encoding="utf-8")

    play = block(setup, "static int play_folder(")
    check("AllowSetForegroundWindow(pi.dwProcessId)" in play, "--play does not let the game come to the front")
    check(play.index("AllowSetForegroundWindow") < play.index("WaitForSingleObject"),
          "the right to the front is passed on only after the game ended")

    shown = display[display.index("ShowWindow(hwnd, SW_SHOW);"):]
    check("SetForegroundWindow(hwnd);" in shown[:600], "the game's window does not ask to come to the front")
    noactivate = display[display.index("if (noactivate)"):display.index("ShowWindow(hwnd, SW_SHOW);")]
    check("SetForegroundWindow" not in noactivate, "HOS_WINDOW_NOACTIVATE would take the front")

    front = block(hid, "static int game_in_front(")
    win = front[front.index("#ifdef _WIN32"):front.index("#endif")]
    for cls in ("Progman", "WorkerW", "Shell_TrayWnd"):
        check('"%s"' % cls in win, "the desktop's or taskbar's class %s takes the input from the game" % cls)
    check("last_normal_was_us" in win, "the desktop would give the game input after the player chose another program")

    poll = block(sdl, "static void pads_poll")
    check("gave_input = 1" in poll and "state_live = live" in poll, "SDL does not tell which pads gave input")
    check(re.search(r"int hos_sdl_pads_live\(void\)", sdl), "no hos_sdl_pads_live")
    pads = block(hid, "static void pads_read(")
    check("hos_sdl_pads_live()" in pads, "XInput does not know whether SDL's pads gave input")
    check(re.search(r"if \(!sdl_pads \|\| sdl_silent \|\| poll_xinput_env\)", pads),
          "XInput stays off while SDL's pads are silent")
    print("handheld controls: ok")


if __name__ == "__main__":
    main()
