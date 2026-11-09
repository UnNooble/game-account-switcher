"""Windows extras: desktop shortcuts and uninstall cleanup."""
import os
from pathlib import Path
import re
import shutil
import subprocess

from . import APP_NAME, launch_command, resource
from .errors import UserError

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def create_desktop_shortcut(profile):
    """Desktop icon that switches straight to this account and starts the game."""
    target, args = launch_command("--play", profile["id"])
    icon = target if target.lower().endswith("valorantswitcher.exe") else str(resource("assets", "icon.ico"))
    name = re.sub(r'[\\/:*?"<>|]', "", f"Play - {profile['label']}").strip() or "Play account"
    env = dict(os.environ, VS_NAME=name, VS_TARGET=target, VS_ARGS=args,
               VS_DIR=str(Path(target).parent), VS_ICON=icon)
    # Values travel in environment variables, never pasted into the script text.
    script = ("$d=[Environment]::GetFolderPath('Desktop');"
              "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d ($env:VS_NAME+'.lnk')));"
              "$s.TargetPath=$env:VS_TARGET;$s.Arguments=$env:VS_ARGS;$s.WorkingDirectory=$env:VS_DIR;"
              "$s.IconLocation=$env:VS_ICON;$s.Description='Switch account and start the game';$s.Save()")
    ps = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run([str(ps), "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                            capture_output=True, timeout=30, creationflags=NO_WINDOW)
    if result.returncode != 0:
        raise UserError("Windows couldn't create the desktop shortcut.")
    return name


def forget_everything(data_root):
    """Used by the uninstaller (only if the user agrees): remove saved logins, passwords and settings."""
    from .store import Store
    from .credentials import Credentials
    root = Path(data_root)
    try:
        ids = [p["id"] for p in Store(root).read()["profiles"]]
    except UserError:
        ids = []
    try:
        creds = Credentials()
        for pid in ids:
            creds.delete(pid)
    except OSError:
        pass
    shutil.rmtree(root, ignore_errors=True)
