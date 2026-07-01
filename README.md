<div align="center">

<br>

# ◈𝐌𝐅𝐋𝐎𝐖

[![Version](https://img.shields.io/badge/Version-v2.5.0-c4a7e7?style=for-the-badge&labelColor=1a1a2e)](https://github.com/MaaruAX/MCopy/releases)
[![Status](https://img.shields.io/badge/Status-Stable-c4a7e7?style=for-the-badge&labelColor=1a1a2e)](https://github.com/MaaruAX/MCopy)
![free](https://img.shields.io/badge/Works_on_FREE_Resolve-1a1a2e?style=for-the-badge&labelColor=1a1a2e)

<br>

**A curve editor for DaVinci Resolve Fusion**

_Shape your keyframes. Apply physics. Works on the free version of DaVinci Resolve._

<br>

![macOS](https://img.shields.io/badge/macOS-ebbcba?style=flat-square&logo=apple&logoColor=1a1a2e)&nbsp;&nbsp;![Linux](https://img.shields.io/badge/Linux-f6c177?style=flat-square&logo=linux&logoColor=1a1a2e)&nbsp;&nbsp;![Windows 11](https://img.shields.io/badge/Windows%2011-9ccfd8?style=flat-square&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0iIzFhMWEyZSI%2BPHBhdGggZD0iTTExLjYwNiAwSDB2MTEuNjA2aDExLjYwNlYwem0xMi4zOTQgMGgtMTEuNjA2djExLjYwNmgxMS42MDZWMHptLTEyLjM5NCAxMi4zOTRIMFYyNC4waDExLjYwNnYtMTEuNjA2em0xMi4zOTQgMGgtMTEuNjA2djExLjYwNmgxMS42MDZWMTIuMzk0eiIvPjwvc3ZnPg%3D%3D)&nbsp;![Python](https://img.shields.io/badge/Python_3.9+-31748f?style=flat-square&logo=python&logoColor=1a1a2e)&nbsp;&nbsp;![Resolve](https://img.shields.io/badge/DaVinci_Reolve_17+-c4a7e7?style=flat-square&logo=davinciresolve&logoColor=1a1a2e)

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

**Option A — Desktop Executable (Windows)**

Download `MFlow-v2.5.0.exe` from the [Releases page](https://github.com/MaaruAX/MCopy/releases). Run standalone with no Python environment needed.

**Option B — Standalone Installer (All Platforms)**

```bash
python install.py
```

The upgraded utility installer lets you selectively install, skip, or update Script utility launchers. Run the tool based on your DaVinci Resolve license level:

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

[![discord](https://img.shields.io/badge/Join_the_Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/dvZ9nvN79Y)

<br>

</details>

---

## ![req](https://img.shields.io/badge/◈_REQUIREMENTS-ebbcba?style=flat-square&labelColor=1a1a2e)

|                                                                                                         |                                                                                                          |
| ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| ![resolve](https://img.shields.io/badge/DaVinci_Resolve_18+-eb6f92?style=flat-square&labelColor=26233a) | Free or Studio releases fully compatible.                                                                |
| ![python](https://img.shields.io/badge/Python_3.9+-c4a7e7?style=flat-square&labelColor=26233a)          | Required for standalone setup scripts. Standalone installer must be sourced from [python.org](https://python.org). |
| ![pyside](https://img.shields.io/badge/PySide6_≥_6.5-9ccfd8?style=flat-square&labelColor=26233a)        | Installed on setup automatically by `install.py` processes.                                                                     |

> ⚠️ **Python from the Microsoft Store will not work.** It is a restricted stub that cannot load the DaVinci Resolve scripting modules. Download the standard installer from **[python.org/downloads](https://python.org/downloads)** and check _"Add Python to PATH"_ during setup.

---

## ![credits](https://img.shields.io/badge/◈_CREDITS-f6c177?style=flat-square&labelColor=1a1a2e)

Inspired and based on **[FFlow](https://github.com/MisonLarp/Fusion-Flow/)** by Mison — the open source Bezier curve editor for Fusion.

---

<div align="center">

<br>

![oss](https://img.shields.io/badge/Free_&_Open_Source-26233a?style=for-the-badge)
&nbsp;
[![discord](https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/dvZ9nvN79Y)
&nbsp;
[![releases](https://img.shields.io/badge/Releases-eb6f92?style=for-the-badge)](https://codeberg.org/MaaruAx/MFlow/releases)

<br>
<sub>**Part of the MMarket ecosystem • Created with love for the DaVinci Resolve community.</sub>
<br><br>

</div>

