# Game Account Switcher: notes for Claude Code

Windows desktop app (Python 3.12, Tkinter) that signs in to the Riot Client as a chosen saved account and starts
VALORANT. Unofficial: never imply Riot endorses it. The owner is a beginner: explain jargon briefly, keep answers
short, and don't make big changes without saying what they are.

## Commands
- Tests (run anywhere): `pip install -r requirements.txt pytest` then `python -m pytest -q`
- Run the app (Windows): `Start.cmd` or `python main.py`
- Build the installer (Windows): `Build-Installer.cmd` (PyInstaller + Inno Setup)
- Release: bump `VERSION` in `switcher/__init__.py` and `AppVersion` in `installer/ValorantSwitcher.iss`, add a
  `CHANGELOG.md` section, then publish a GitHub release with tag `vX.Y.Z`. GitHub Actions builds the Setup .exe.

## Layout
- `switcher/engine.py` the switch / sign-in steps (runs on a worker thread; asks the UI via `ask(kind, data)`)
- `switcher/riot.py` finding/closing/starting Riot, its local API, Deceive launch
- `switcher/riotui.py` + `assets/riot_ui.ps1` fill Riot's sign-in window with Windows UI Automation (password goes over stdin only)
- `switcher/vault.py` allowlisted login-file snapshots, DPAPI encryption, crash-recovery journal
- `switcher/store.py` profiles.json; `credentials.py` Windows Credential Manager; `portable.py` encrypted backup/restore
- `switcher/ui.py`, `widgets.py`, `theme.py` Tkinter UI (custom rounded widgets); `updates.py` GitHub update check
- `tests/` engine tests use a simulated Riot Client (`FakeRiot` in `test_engine.py`); `test_ui_real.py` needs a real display

## Rules
- Never commit or print secrets: passwords, tokens, saved sessions, `*.vasbak` backups, private keys. `.gitignore` covers them.
- Don't push, tag or publish to GitHub unless the owner asks. Commit author email must be the GitHub noreply address.
- Don't touch Vanguard, game files, the firewall or UAC. Never sign out of Riot (it revokes the saved login).
- Keep it free and non-commercial (Riot's fan-project rules): no ads, donations, paywalls or license keys.
- Keep Riot's non-endorsement notice and trademark line (README, TERMS.txt, footer). Don't put "valorant" in app names or GitHub topics.
- Deceive is a separate GPL-3.0 program the user downloads themselves. Don't bundle, modify or link it into our code.
- Internal names stay for compatibility: `ValorantSwitcher.exe`, data folder `%LOCALAPPDATA%\ValorantProfiles`,
  Credential Manager target `ValorantSwitcher/`. The visible app name is in `APP_NAME`.
- Riot changes its client often. Verify against real behavior on a Windows PC; the logs are in the data folder (`log.txt`, no secrets).
