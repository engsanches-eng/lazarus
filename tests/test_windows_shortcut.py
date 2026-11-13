"""(lazarus) The Windows installer makes one desktop shortcut to the game itself, with the ocarina, and says when the game
is already installed (builder/HookshotBuilder: Finder.cs, MainWindow.xaml(.cs), HookshotBuilder.csproj).

python -I -B tests/test_windows_shortcut.py
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
B = ROOT / "builder" / "HookshotBuilder"


def check(ok, message):
    if not ok:
        raise SystemExit("FAIL: " + message)


def main():
    finder = (B / "Finder.cs").read_text(encoding="utf-8")
    window = (B / "MainWindow.xaml.cs").read_text(encoding="utf-8")
    xaml = (B / "MainWindow.xaml").read_text(encoding="utf-8")
    proj = (B / "HookshotBuilder.csproj").read_text(encoding="utf-8")

    check('LinkName = "The Legend of Zelda - Ocarina of Time.lnk"' in finder, "the shortcut is not named after the game")
    check('Path.Combine(gameFolder, "bin", "hookshot.exe")' in finder and "var exe = File.Exists(game) ? game" in finder,
          "the shortcut does not start the game itself")
    check('"lazarus.ico"' in finder and "icon = kept;" in finder, "the shortcut's icon is not the ocarina")
    check('<None Include="lazarus.ico" CopyToOutputDirectory="PreserveNewest" />' in proj, "lazarus.ico is not shipped")

    ico = (B / "lazarus.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    check(reserved == 0 and kind == 1 and count >= 4, "lazarus.ico is not an icon with several sizes")
    sizes = {(ico[6 + 16 * i] or 256) for i in range(count)}
    check({16, 32, 48, 256} <= sizes, "lazarus.ico lacks a size Windows uses: %s" % sorted(sizes))

    check(window.count("Finder.Shortcuts(finished, !BuilderHome.Portable, false)") == 2,
          "a build or an update makes a Start menu entry, or no desktop shortcut")
    check('"The game is already installed"' in window and 'BuildButton.Content = "Close installer";' in window,
          "an installed game is not said to be installed")
    up = window[window.index("case Mode.UpToDate:   // ((lazarus) the desktop shortcut"):]
    check("Close();" in up[:400] and "Play(" not in up[:400], "the installed game's button does not close the installer")
    check('Click="CloseInstaller"' in xaml and 'Text="Close installer"' in xaml, "the ready page still offers Play")
    check('x:Name="StartTick"' in xaml and 'IsChecked="False"' in xaml, "a Start menu entry is ticked")
    print("windows shortcut: ok")


if __name__ == "__main__":
    main()
