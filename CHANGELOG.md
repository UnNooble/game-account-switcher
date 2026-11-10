# Changelog

## 3.8.0
- Roomier window: larger default and minimum size, the header split into two rows (title and buttons, then the hint and the Appear offline switch), and more space around cards and buttons.
- The app is now called *Game Account Switcher* (no Riot trademarks in its name). The installer is `GameAccountSwitcher-Setup-x.y.z.exe`, shows the terms before installing, and includes the license and third-party notices. The in-app footer and README carry Riot's non-endorsement notice.
- Appear offline: a switch at the top of the window. When it's on, the app launches the game through Deceive, which hides your chat status from friends. Deceive is a separate free program: the first time you turn the switch on, the app opens its official download page and then finds the downloaded `Deceive.exe` for you. ··· → *Appear offline setup* repeats this.
- Stats overlay: a second switch at the top. When it's on, the app starts Overwolf with the game so the Tracker overlay shows in-game. Overwolf and the Tracker app are separate free programs: the first time, the app opens the official download page and then finds them for you. ··· → *Stats overlay setup* repeats this.
- The taskbar now shows the app's own icon instead of the Python one.

## 3.7.0
- Update notice: the app checks GitHub once a day for a newer release and shows a "Version X is available" banner with a Download button. ··· → *Check for updates* checks on demand, and *Automatic update check* turns it off. One anonymous request, no account data; silent when offline. Works once the repository's releases are public.

## 3.6.3
- `Build-Installer.cmd` opens the installer window when it finishes (Next > Finish, desktop icon ticked).

## 3.6.2
- The verification code is typed one digit per box and read back to check (it used to be pasted into one box and landed shifted).
- The code box says where Riot sent the code: email (with the partly hidden address), Riot Mobile, authenticator or text message.
- A "resend" button is never pressed by mistake.

## 3.6.1
- Fixed "couldn't fill in the Riot window": on current Riot Clients the process is named `Riot Client` (with a space) and the script only accepted `RiotClient*`. It now matches the process, not the title, and logs what Windows can see if nothing matches.

## 3.6.0
- Riot removed the background login service (it answers HTTP 404), so the app now fills in Riot's own sign-in window: it sets the username and password boxes, ticks "Stay signed in" and presses the arrow using Windows UI Automation. No keystrokes or mouse clicks are simulated.
- The password goes to the bundled PowerShell script (`assets/riot_ui.ps1`) over stdin only.
- 2FA codes and Riot Mobile approvals are asked for in the app and entered into Riot's window for you. "Email me a code instead" is offered on the Riot Mobile page. Captchas still need you.

## 3.5.3
- When Riot refuses the automatic sign-in, the message and log say why (HTTP code and Riot's error name, never the password).

## 3.5.2
- Add Account needs only username + password (name optional).
- Adding an account that already exists refreshes it and plays it instead of failing.

## 3.5.1
- The ··· menus close when you click elsewhere, press Esc, or click the button again.
- The game starts sooner after a first-time or re-sign-in: the app asks Riot to start the game right after sign-in instead of waiting ~25 s, and saves the login while the game is starting.

## 3.5
- Redesigned window: larger default size, one clear list, two buttons up top (Add Account and ···), rounded buttons and cards, questions asked in small in-app sheets.
- If the game is already open and you pick another account, the app asks "Close the game and switch?".

## 3.4
- 2FA handled inside the app (code box, or wait for Riot Mobile).

## 3.3
- Backup / Restore to move your own accounts to another PC or USB stick (passphrase-encrypted, scrypt + authenticated AES).
- "Check logins" status panel.

## 3.2
- Real Windows installer (Start menu, desktop icon, uninstaller, no Python needed), app icon, per-account desktop shortcuts, uninstall cleanup option.
- "Save the account that's already signed in".

## 3.0 – 3.1 (from 2.x)
- One Riot restart per switch instead of two; recognises the newer `Riot Client.exe` process; shows each account's Riot ID; duplicate-account detection; offline token refresh; slow PowerShell signature check replaced by install-folder checks; old mouse-automation leftovers removed.
