# Game Account Switcher

**Pick an account → Riot Client signs in as that account → your game starts.**
A small Windows app for people with more than one Riot account.

<h2 align="center">
  <a href="https://github.com/UnNooble/game-account-switcher/releases/latest">
    <img alt="Download for Windows" width="460" src="https://img.shields.io/badge/%E2%AC%87%20%20DOWNLOAD%20FOR%20WINDOWS-latest%20version-ff4655?style=for-the-badge&logo=windows&logoColor=white">
  </a>
</h2>

<p align="center"><b><a href="https://github.com/UnNooble/game-account-switcher/releases/latest">Click here</a></b>, then under <b>Assets</b> on the page that opens, download <code>GameAccountSwitcher-Setup-x.y.z.exe</code> and run it.<br>
While the repository is private, only people you've added as collaborators can open it.</p>

> **Unofficial.** Game Account Switcher isn't endorsed by Riot Games and doesn't reflect the views or opinions
> of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games,
> VALORANT and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
> Use it only with your own accounts and follow Riot's Terms of Service. See [TERMS.txt](TERMS.txt).

![platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0f1923)
![python](https://img.shields.io/badge/python-3.12-ff4655)
![status](https://img.shields.io/badge/status-private%20beta-17222e)

## Features

- **One-click switching.** Click a card and the game starts on that account.
- **Hands-off first sign-in.** Enter username and password once. The app fills in Riot's sign-in window,
  ticks *Stay signed in*, presses the arrow, and launches the game.
- **Stats overlay.** Optional switch that opens the Valorant Tracker app (through Overwolf) with the game so its overlay shows in-game. Overwolf and the Tracker app are separate programs you install once.
- **2FA inside the app.** Email, text and authenticator codes are asked for in the app and typed into Riot
  for you, one digit per box. The prompt tells you where Riot sent the code (email shows the partly
  hidden address). For Riot Mobile you approve on your phone, or ask for an email code instead.
- **Self-healing logins.** If a saved login expires, the app signs in again with the saved password.
- **Real installer.** Setup wizard, Start menu entry, desktop icon, uninstaller. No Python needed.
- **Backup / restore.** Move your own accounts to another PC with a passphrase-encrypted file.
- **Appear offline.** A switch at the top of the window hides your chat status from friends. It uses
  [Deceive](https://github.com/molenzwiebel/Deceive), a separate free open-source program that you download
  once (the app opens its official download page and finds the file for you). It is unofficial and can break
  when Riot changes its chat.
- **Update notice.** A banner appears when a newer release is on GitHub (checked each time the app opens; can be turned off in ···).
- **Per-account desktop shortcuts** that switch and launch in one double-click.
- **Crash-safe.** File swaps are journaled and restored automatically after a crash or power loss.

## Install

1. Download `GameAccountSwitcher-Setup-<version>.exe` from the [**Releases** page](https://github.com/UnNooble/game-account-switcher/releases/latest) (under *Assets*).
2. Run it: Next → Install → Finish. No admin rights needed.
3. Windows may show "Windows protected your PC" because the installer isn't code-signed yet.
   Click **More info → Run anyway**.

Uninstall from **Settings → Apps**. The uninstaller asks whether to also delete saved accounts (default: keep).

## Use

1. **Add Account** → username and password (a display name is optional) → *Add & Sign In*.
2. The app signs in, saves the login and starts the game. Complete a captcha yourself if Riot shows one.
3. Repeat for each account. Afterwards click **Play** on a card.
4. Top-right **···**: Check logins, Back up accounts, Restore from backup, Riot Client location, Appear offline setup, Open log file, Check for updates.
5. A card's **···**: Rename, Username & password, Sign in again, Add desktop shortcut, Forget saved password, Move up/down, Remove account.

Rules of thumb:
- Close the game before switching (the app asks and can close it for you).
- Never press **Sign out** in Riot. It invalidates the saved login on Riot's servers.
- Run Riot and this app normally, not as administrator.

## How it works

Riot keeps a remembered login in `%LOCALAPPDATA%\Riot Games\Riot Client\Data\` when *Stay signed in* is
ticked. The app keeps one encrypted copy of those files per account and swaps them while Riot is closed.

```
click PLAY on "Alt"
 ├─ game running?  → ask to close it
 ├─ ask Riot (local API) who is signed in → close Riot politely
 ├─ re-save the outgoing account's files (Riot rotates tokens)
 ├─ journal current files → copy Alt's files in (atomic, crash-recoverable)
 ├─ start Riot with --launch-product=valorant (same as the official shortcut)
 └─ confirm via local API that Riot signed in as Alt → wait until the game runs
```

**First sign-in / expired login.** Riot removed its background login endpoint, so the app drives Riot's own
sign-in window through **Windows UI Automation** (the accessibility interface): it sets the username and
password fields, ticks the checkbox and invokes the arrow button. No keystrokes or mouse clicks are
simulated. The work is done by `assets/riot_ui.ps1`, which receives its request, including the password,
over stdin only (never on a command line or in a file).

**What it touches:** the allowlisted Riot login files, start/stop of Riot Client, Riot's local API on
`127.0.0.1`, Windows Credential Manager entries named `ValorantSwitcher/...`, and its own data folder.
It never touches Vanguard (`vgc`), the game, game memory, the firewall, Defender or UAC. It does not try
to bypass captchas or 2FA.

## Security and privacy

- Saved logins are encrypted with Windows DPAPI: only your Windows user on this PC can read them. That stops
  copying the folder to another PC; it does **not** stop malware already running as you.
- Passwords live in Windows Credential Manager, are optional, and can be removed per account.
- Backups use scrypt + authenticated AES-Fernet with your passphrase. They still contain working logins:
  treat them like passwords. There is no recovery if the passphrase is lost.
- `log.txt` holds steps, status codes and file sizes only, never passwords or tokens.
- Never share `%LOCALAPPDATA%\ValorantProfiles`: its files are effectively logged-in sessions.
- Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## Troubleshooting

1. **···** → **Open log file** and read the last lines.
2. `login file ... token=no` after signing in → *Stay signed in* wasn't ticked. Use the card's ··· → *Sign in again*.
3. Couldn't fill in the Riot window → the log lists the windows Windows can see; open an issue with it.
4. `local API GET /rso-auth/v1/authorization -> 404` and no "signed-in account detected" → Riot changed its
   local API again. An app update is needed.

| Risk | How the app handles it |
|---|---|
| Captcha shown by Riot | Asks you to finish it in the Riot window, then continues |
| Riot changes its window or local API | Fails safely with a message; never launches an unverified account |
| Riot running as administrator | Asks you to close it; run both normally |
| Antivirus briefly locks files | Retries; the journal restores previous files if interrupted |
| Vanguard needs a reboot | Reports it; never touches Vanguard |
| SmartScreen / antivirus flags the unsigned EXE | Expected until the build is code-signed |
| Different PC or Windows user | Saved logins can't be decrypted (by design). Use Backup / Restore |

## Future updates

- Support for more game launchers, starting with Steam and Epic Games.
- Automatic in-app updates.
- A code-signed installer, so Windows shows no warning.

## Data locations

- `%LOCALAPPDATA%\ValorantProfiles\profiles.json` – names, Riot IDs, settings (no secrets)
- `%LOCALAPPDATA%\ValorantProfiles\sessions\*.bin` – encrypted saved logins
- `%LOCALAPPDATA%\ValorantProfiles\log.txt` – diagnostics

## Development

```
main.py                  entry point (single-instance; --play <id>, --forget-everything)
switcher/engine.py       the switch / sign-in steps
switcher/riot.py         find/close/open Riot, local API, launch
switcher/updates.py      GitHub release check for the update banner
switcher/riotui.py       Python side of the UI Automation sign-in
assets/riot_ui.ps1       UI Automation script (fill, code, click, inventory)
switcher/vault.py        allowlisted file snapshot/restore, DPAPI, recovery journal
switcher/store.py        profiles.json
switcher/credentials.py  Windows Credential Manager
switcher/portable.py     passphrase-encrypted backup / restore
switcher/ui.py, widgets.py, theme.py   Tkinter UI
installer/*.iss          Inno Setup script
tests/                   engine tests against a simulated Riot Client
```

```
pip install -r requirements.txt pytest
python -m pytest -q          # engine tests run anywhere; the Tk test needs a display
python main.py               # run from source on Windows (or Start.cmd)
```

**Build the installer locally:** double-click `Build-Installer.cmd` (Windows). It runs PyInstaller, installs
Inno Setup if missing, and writes `dist\GameAccountSwitcher-Setup-<version>.exe`.

## Releasing

1. Bump `VERSION` in `switcher/__init__.py` and `AppVersion` in `installer/ValorantSwitcher.iss`; add a
   [CHANGELOG](CHANGELOG.md) entry.
2. Commit, then `git tag vX.Y.Z && git push --tags`.
3. GitHub Actions (`.github/workflows/build.yml`) runs the tests on Windows, builds the installer and
   attaches `GameAccountSwitcher-Setup-X.Y.Z.exe` to the release.

Running a newer Setup over an older install updates in place; accounts, logins and passwords are kept.

### Code signing
Unsigned installers trigger SmartScreen and some antivirus false positives. A certificate fixes that
(free for open-source via SignPath Foundation, or a paid standard/EV certificate), then sign the EXE and
installer with `signtool` in the build.

## Third-party software

- **Deceive** (GPL-3.0): optional, **not included** in this app or its installer. The user downloads it from its
  official page, <https://github.com/molenzwiebel/Deceive>, and this app only starts it as its own process.

## Privacy

No analytics, tracking or accounts. Saved logins and settings stay on your PC. The only network requests this app
makes itself are the optional once-a-day update check to GitHub (turn it off in ··· → Automatic update check).
Signing in is done by Riot's own client. Details: [TERMS.txt](TERMS.txt), section 3.

## Legal

- Copyright (c) 2026 UnNooble. All rights reserved ([LICENSE](LICENSE)). Free for personal use under
  [TERMS.txt](TERMS.txt); the installer shows these terms before installing.
- Third-party software and trademarks: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Riot Games, VALORANT and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
  This project isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone
  officially involved in producing or managing Riot Games properties.

## Disclaimer

Provided as is, without warranty. Riot Games has not approved third-party account switchers, so using one is at
your own risk and your responsibility under Riot's Terms of Service.
