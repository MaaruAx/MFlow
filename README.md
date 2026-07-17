<div align="center">

<br>

# ◈𝐌𝐅𝐋𝐎𝐖

[![Version](https://img.shields.io/badge/Version-v2.6.1-c4a7e7?style=for-the-badge&labelColor=1a1a2e)](https://github.com/MaaruAX/MFlow/releases)
[![Downloads](https://img.shields.io/endpoint?url=https://codeberg.org/MaaruAx/MFlow/raw/branch/pages/downloads.json&style=for-the-badge&labelColor=1a1a2e)](https://codeberg.org/MaaruAx/MFlow/releases)
[![Status](https://img.shields.io/badge/Status-Stable-c4a7e7?style=for-the-badge&labelColor=1a1a2e)](https://github.com/MaaruAX/MFlow)

![free](https://img.shields.io/badge/Works_on_FREE_Resolve-1a1a2e?style=for-the-badge&labelColor=1a1a2e)

<br>

**A curve editor for DaVinci Resolve Fusion**

_Shape your keyframes. Apply physics. Works on the free version of DaVinci Resolve._

<br>

![macOS](https://img.shields.io/badge/macOS-ebbcba?style=flat-square&logo=apple&logoColor=1a1a2e)&nbsp;&nbsp;![Linux](https://img.shields.io/badge/Linux-f6c177?style=flat-square&logo=linux&logoColor=1a1a2e)&nbsp;&nbsp;![Windows 11](https://img.shields.io/badge/Windows%2011-9ccfd8?style=flat-square&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0iIzFhMWEyZSI%2BPHBhdGggZD0iTTExLjYwNiAwSDB2MTEuNjA2aDExLjYwNlYwem0xMi4zOTQgMGgtMTEuNjA2djExLjYwNmgxMS42MDZWMHptLTEyLjM5NCAxMi4zOTRIMFYyNC4waDExLjYwNnYtMTEuNjA2em0xMi4zOTQgMGgtMTEuNjA2djExLjYwNmgxMS42MDZWMTIuMzk0eiIvPjwvc3ZnPg%3D%3D)&nbsp;![Python](https://img.shields.io/badge/Python_3.9+-31748f?style=flat-square&logo=python&logoColor=1a1a2e)&nbsp;&nbsp;![Resolve](https://img.shields.io/badge/DaVinci_Reolve_17+-c4a7e7?style=flat-square&logo=davinciresolve&logoColor=1a1a2e)

<br>

</div>

---

<div align="center">

<br>

### ◈ 𝐒𝐔𝐏𝐏𝐎𝐑𝐓 𝐔𝐒

[![kofi](https://img.shields.io/badge/_Support_me_on_Ko--fi-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white&labelColor=1a1a2e)](https://ko-fi.com/theoldhyaenidae)

<br>

</div>

---

## ![feat](https://img.shields.io/badge/◈_WHAT_IS_MFLOW-eb6f92?style=flat-square&labelColor=1a1a2e)

**MFlow** is a floating panel that lets you draw bezier curves, dial in physics, and push them directly into Resolve's splines with one click — no Studio license required, works on the free version of DaVinci Resolve.

<table>
<tr>
<td>

![curves](https://img.shields.io/badge/Nine_Curve_Modes-c4a7e7?style=flat-square&labelColor=26233a)

```
Bezier    → Handles + custom overshoot
Spring    → Real harmonic oscillator
Elastic   → Amplitude + Period curves
Bounce    → Damped cosine wave impacts
Catenary  → Gravity-tension cable lines
Pulse     → Intermittent periodic waves
Noise     → Seeded organic jitter
Resonance → Forced amplitude physical growth
OKF       → Multi-segment bezier nodes
```

</td>
<td>

![workflow](https://img.shields.io/badge/Built_For_Your_Flow-9ccfd8?style=flat-square&labelColor=26233a)

```
Launches from Resolve's script menu
Detects your active tool automatically
Updates live as you work
Compact mode for minimal footprint
Detachable floating panels
```

</td>
</tr>
</table>

---

## ![modes](https://img.shields.io/badge/◈_CURVE_MODES-f6c177?style=flat-square&labelColor=1a1a2e)

![bezier](https://img.shields.io/badge/Bezier-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Pull two handles freely across the curve preview. Enable overshoot options to extend past standard boundaries for natural spring back animations.

![spring](https://img.shields.io/badge/Spring-f6c177?style=flat-square&labelColor=26233a) &nbsp;A physical damped harmonic oscillator engine that bakes realistic bouncing curves into keyframes based on mass, stiffness, and dynamic project framerates.

![elastic](https://img.shields.io/badge/Elastic-eb6f92?style=flat-square&labelColor=26233a) &nbsp;Penner elastic equations with custom parameters. Includes a preloaded database containing standard curves like "rubber band" or "snappy".

![bounce](https://img.shields.io/badge/Bounce-c4a7e7?style=flat-square&labelColor=26233a) &nbsp;Simulates physical bounces with ceiling (1.0 limit) or floor (0.0 limit) options. Tweak decay and frequency interactively on the preview canvas.

![catenary](https://img.shields.io/badge/Catenary-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Models hanging heavy wires under gravity. Adjust sagging intensity from a straight line to steep mathematical drops directly via mouse-dragging.

![pulse](https://img.shields.io/badge/Pulse-f6c177?style=flat-square&labelColor=26233a) &nbsp;Creates repeated, periodic bursts of wave motion separated by quiet resting sections. Full frequency, tempo, and sharpness controls.

![noise](https://img.shields.io/badge/Noise-eb6f92?style=flat-square&labelColor=26233a) &nbsp;Generates organic, continuous pseudo-random keyframe jitter based on seedable mathematical models.

![resonance](https://img.shields.io/badge/Resonance-c4a7e7?style=flat-square&labelColor=26233a) &nbsp;Models forced physical oscillation over time. Features on-canvas adjustments for damping and drive constants.

![okf](https://img.shields.io/badge/OKF-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Injects intermediate keyframes between major boundaries. Uses relative-space projections to ensure handle coordinates stay distortion-free.

---

## ![features](https://img.shields.io/badge/◈_FEATURES-9ccfd8?style=flat-square&labelColor=1a1a2e)

![oncanvas](https://img.shields.io/badge/On--Canvas_Controls-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Control parameters interactively by clicking and dragging directly on the curve canvas (e.g., Bounce Decay/Frequency or Catenary Tension).

![presets](https://img.shields.io/badge/Library_Context_Menus-f6c177?style=flat-square&labelColor=26233a) &nbsp;Double-click preset cards to instantly write curves. Right-click to duplicate (with automatic name increments), rename, or delete library profiles.

![dbtools](https://img.shields.io/badge/Presets_Export_&_Sort-eb6f92?style=flat-square&labelColor=26233a) &nbsp;Sort your presets alphabetically, back up your personal presets, or batch-import libraries through a collapsible options drawer.

![oversampling](https://img.shields.io/badge/Sub--Frame_Oversampling-c4a7e7?style=flat-square&labelColor=26233a) &nbsp;Bake ultra-precise, high-density keyframes (1x to 8x density scale) to produce fluid, high-frequency motion paths inside Resolve.

![autoapply](https://img.shields.io/badge/Live_Auto--Apply-eb6f92?style=flat-square&labelColor=26233a) &nbsp;Apply active curves live instantly as you drag points, edit values, or switch math modes without clicking execution buttons.

![fuzzysnap](https://img.shields.io/badge/Fuzzy_Playhead_Snapping-c4a7e7?style=flat-square&labelColor=26233a) &nbsp;Engine automatically identifies and snaps to the closest active keyframe interval if the playhead sits outside boundary thresholds.

---

## ![themes](https://img.shields.io/badge/◈_THEMES-c4a7e7?style=flat-square&labelColor=1a1a2e)

Eight themes bundled out of the box:

![rp](https://img.shields.io/badge/Rosé_Pine-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;
![cat](https://img.shields.io/badge/Catppuccin_Mocha-85c1dc?style=flat-square&labelColor=26233a) &nbsp;
![drac](https://img.shields.io/badge/Dracula-eb6f92?style=flat-square&labelColor=26233a) &nbsp;
![nord](https://img.shields.io/badge/Nord-282a36?style=flat-square&labelColor=26233a) &nbsp;
![kana](https://img.shields.io/badge/Kanagawa-e6c384?style=flat-square&labelColor=26233a) &nbsp;
![gruv](https://img.shields.io/badge/Gruvbox_Material_Dark-d4be98?style=flat-square&labelColor=26233a) &nbsp;
![ff](https://img.shields.io/badge/FFlow_1.0-e05828?style=flat-square&labelColor=26233a)

You can also build your own theme and export it as a `.json` file to share or keep across reinstalls. The interface zoom, preset grid columns, and border radius are all configurable independently of the theme.

---

## ![install](https://img.shields.io/badge/◈_INSTALLATION-c4a7e7?style=flat-square&labelColor=1a1a2e)

**Option A — Windows Installer (recommended on Windows)**

Download `MFlow-v2.6.1-x64-Setup.exe` from the [Releases page](https://codeberg.org/MaaruAx/MFlow/releases). It's a checkbox installer — pick any combination of the three components below, run it, done.

| Component                                                                                             | What it does                                                                      |
| ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| ![standalone](https://img.shields.io/badge/Standalone_App-9ccfd8?style=flat-square&labelColor=26233a) | Installs the desktop app — works on its own, no Resolve required.                 |
| ![studio](https://img.shields.io/badge/Studio-eb6f92?style=flat-square&labelColor=26233a)             | Adds MFlow to `Workspace → Scripts → MFlow` — any page, DaVinci Resolve Studio.   |
| ![free](https://img.shields.io/badge/Free-9ccfd8?style=flat-square&labelColor=26233a)                 | Adds MFlow to `Fusion page → Comp → Scripts → MFlow_Free` — DaVinci Resolve Free. |

<details>
<summary><img src="https://img.shields.io/badge/How_does_it_work%3F-f6c177?style=flat-square&labelColor=26233a" alt="how"></summary>

<br>

The installer itself is small — it only embeds the plain source files needed for the Resolve integration (`main.py`, `core/`, `ui/`, presets, themes, language files). Nothing there needs Python installed separately or an internet connection; it's copied straight to `%APPDATA%\MFlow` if you check Studio and/or Free, and the matching bridge file (`MFlow.lua` for Studio, `MFlow_Free.py` for Free) is dropped into Resolve's own `Scripts` folder so it shows up in the menu.

If you check **Standalone App**, the installer downloads the compiled desktop build from Cloudflare R2 during setup (that's why it needs an internet connection for that step specifically) and extracts it straight into the install folder you chose. That download is verified automatically against a SHA-256 checksum baked into the installer at build time — if the downloaded bytes don't match, Setup flags it instead of silently installing a corrupted or tampered file. The exact file name and its expected hash are both shown on the "Ready to Install" screen before anything downloads, and you can cross-check that hash by hand against the one published in each release's changelog. See the **Verify Release Authenticity** section below for the full verification steps if you want to confirm it came from this project specifically.

If you skip a component, nothing related to it is downloaded, copied, or touched — checking only "Free", for example, never installs the standalone app or touches Resolve's Studio-only Scripts folder.

Uninstalling removes everything from the install folder; it separately asks whether to also delete your saved presets/themes/settings in `%APPDATA%\MFlow`, so you can uninstall and reinstall without losing your data if you say no.

<br>

</details>

**Option B — Manual Installer Script (macOS, Linux, or manual setup)**

```bash
python install.py
```

This cross-platform utility installer lets you selectively install, skip, or update Script utility launchers. Run the tool based on your DaVinci Resolve license level:

| License                                                                                   | Execution Area                                   |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------ |
| ![studio](https://img.shields.io/badge/Studio-eb6f92?style=flat-square&labelColor=26233a) | Any window → `Workspace → Scripts → MFlow`       |
| ![free](https://img.shields.io/badge/Free-9ccfd8?style=flat-square&labelColor=26233a)     | Fusion workspace only → `Scripts → Comp → MFlow` |

<details>
<summary><img src="https://img.shields.io/badge/Manual_Install_/_Troubleshooting-f6c177?style=flat-square&labelColor=26233a" alt="manual"></summary>

<br>

**Studio Script Launch** — Copy `MFlow.lua` and its companion `python_path.txt` config file to:

| Platform                                                              | Destination Directory                                                                     |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| ![win](https://img.shields.io/badge/Windows-9ccfd8?style=flat-square) | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`             |
| ![mac](https://img.shields.io/badge/macOS-ebbcba?style=flat-square)   | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/` |
| ![lnx](https://img.shields.io/badge/Linux-f6c177?style=flat-square)   | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/`                                   |

**Free Script Launch** — Copy `MFlow_Free.py` and `mflow_path.txt` inside the `Scripts/Comp/` directories instead.

To initialize directly from your terminal:

```bash
python main.py
```

To clean installation files without wiping your saved curves, profiles, and custom interface schemes:

```bash
python uninstall.py
```

<br>

> **Trouble connecting?** Join our Discord Server below. Provide your active operating system, host python version, and console outputs for immediate setup assistance.

[![discord](https://img.shields.io/badge/Join_the_Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/N5fTEDumSu)

<br>

</details>

<details>
<summary><img src="https://img.shields.io/badge/Verify_Release_Authenticity-9ccfd8?style=flat-square&labelColor=26233a" alt="verify"></summary>

<br>

Every release is GPG-signed. Alongside the installer, each release includes `SHA256SUMS.txt` and `SHA256SUMS.txt.asc` — use them to confirm the file you downloaded is exactly what was published here, unmodified in transit or on the server.

**Public key fingerprint:**

```
3B48 59FF A129 4797 4836  ADB4 8130 B8F7 C0C7 FAEB
```

**1. Import the public key** — either works:

```bash
# From the key file included in this repo
gpg --import mmarket-pubkey.asc

# Or from a keyserver
gpg --keyserver keys.openpgp.org --recv-keys 3B4859FFA12947974836ADB48130B8F7C0C7FAEB
```

**2. Verify the signature** — confirms `SHA256SUMS.txt` itself hasn't been altered and genuinely came from this key:

```bash
gpg --verify SHA256SUMS.txt.asc SHA256SUMS.txt
```

Look for `Good signature from "..."` in the output.

**3. Check the file you downloaded against the published hash:**

```bash
# Linux / macOS
sha256sum -c SHA256SUMS.txt

# Windows (PowerShell)
Get-FileHash .\MFlow-v2.6.1-x64-Setup.exe -Algorithm SHA256
```

The result should match the corresponding line in `SHA256SUMS.txt` exactly.

> The installer also downloads a standalone build from Cloudflare R2 during setup. That download is verified automatically (SHA-256 check built into the installer), and its expected hash is shown on the installer's "Ready to Install" screen if you want to compare it by hand too.

<br>

</details>

---

## ![req](https://img.shields.io/badge/◈_REQUIREMENTS-ebbcba?style=flat-square&labelColor=1a1a2e)

|                                                                                                         |                                                                                                                    |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| ![resolve](https://img.shields.io/badge/DaVinci_Resolve_18+-eb6f92?style=flat-square&labelColor=26233a) | Free or Studio releases fully compatible.                                                                          |
| ![python](https://img.shields.io/badge/Python_3.9+-c4a7e7?style=flat-square&labelColor=26233a)          | Required for standalone setup scripts. Standalone installer must be sourced from [python.org](https://python.org). |
| ![pyside](https://img.shields.io/badge/PySide6_≥_6.5-9ccfd8?style=flat-square&labelColor=26233a)        | Installed on setup automatically by `install.py` processes.                                                        |

> ⚠️ **Python from the Microsoft Store will not work.** It is a restricted stub that cannot load the DaVinci Resolve scripting modules. Download the standard installer from **[python.org/downloads](https://python.org/downloads)** and check _"Add Python to PATH"_ during setup.

---

## ![credits](https://img.shields.io/badge/◈_CREDITS-f6c177?style=flat-square&labelColor=1a1a2e)

Inspired and based on **[FFlow](https://github.com/MisonLarp/Fusion-Flow/)** by Mison — the open source Bezier curve editor for Fusion.

---

<div align="center">

<br>

![oss](https://img.shields.io/badge/Free_&_Open_Source-26233a?style=for-the-badge)
&nbsp;
[![discord](https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/N5fTEDumSu)
&nbsp;
[![releases](https://img.shields.io/badge/Releases-eb6f92?style=for-the-badge)](https://codeberg.org/MaaruAx/MFlow/releases)

<br>
<sub>Part of the MMarket ecosystem • Created with love for the DaVinci Resolve community.</sub>
<br><br>

</div>
