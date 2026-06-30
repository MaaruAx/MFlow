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

![Windows](https://img.shields.io/badge/Windows-9ccfd8?style=flat-square&logo=windows&logoColor=1a1a2e)
&nbsp;
![macOS](https://img.shields.io/badge/macOS-ebbcba?style=flat-square&logo=apple&logoColor=1a1a2e)
&nbsp;
![Linux](https://img.shields.io/badge/Linux-f6c177?style=flat-square&logo=linux&logoColor=1a1a2e)
&nbsp;
![Python](https://img.shields.io/badge/Python_3.9+-c4a7e7?style=flat-square&logo=python&logoColor=1a1a2e)
&nbsp;
![Resolve](https://img.shields.io/badge/DaVinci_Resolve_18+-eb6f92?style=flat-square&logoColor=1a1a2e)

<br>

</div>

---

## ![feat](https://img.shields.io/badge/◈_WHAT_IS_MFLOW-eb6f92?style=flat-square&labelColor=1a1a2e)

**MFlow** is a floating panel that lets you draw bezier curves, dial in physics, and push them directly into Resolve's splines with one click — no Studio license required, works on the free version of DaVinci Resolve.

<table>
<tr>
<td>

![curves](https://img.shields.io/badge/Four_Curve_Modes-c4a7e7?style=flat-square&labelColor=26233a)

```
Bezier         →  free handles + overshoot
Spring         →  mass · stiffness · damping
Elastic        →  amplitude + period
Overkeyframe   →  bezier with mid control points
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

![bezier](https://img.shields.io/badge/Bezier-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Pull two handles freely across the curve. Enable overshoot to push beyond the 0–1 range and get natural overshoots and anticipations.

![spring](https://img.shields.io/badge/Spring-f6c177?style=flat-square&labelColor=26233a) &nbsp;A real damped harmonic oscillator runs under the hood. Set mass, stiffness, damping and initial velocity — MFlow integrates the physics frame by frame and bakes the result directly into your spline keyframes.

![elastic](https://img.shields.io/badge/Elastic-eb6f92?style=flat-square&labelColor=26233a) &nbsp;Penner elastic easing with adjustable amplitude and period. Snappier and more predictable than Spring, great for UI and graphic elements.

![overkeyframe](https://img.shields.io/badge/OKF-c4a7e7?style=flat-square&labelColor=26233a) &nbsp;Adds intermediate keyframes between your two main keys and lets you control each sub-segment independently. Complex curves that would normally take many manual keyframes, built in seconds.

---

## ![features](https://img.shields.io/badge/◈_FEATURES-9ccfd8?style=flat-square&labelColor=1a1a2e)

![kfrange](https://img.shields.io/badge/Keyframe_range_selector-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Choose exactly which keyframe segment to apply the curve to using the FROM / TO controls — not limited to the outermost pair.

![compact](https://img.shields.io/badge/Compact_mode-f6c177?style=flat-square&labelColor=26233a) &nbsp;Toggle between the full editor (940×580) and a minimal view (460×480) that shows only the curve canvas. Useful when screen space is tight.

![autoapply](https://img.shields.io/badge/Auto--apply-eb6f92?style=flat-square&labelColor=26233a) &nbsp;Optionally apply the curve automatically every time you adjust a handle or parameter, without clicking Apply.

![multicomp](https://img.shields.io/badge/Multi--comp_support-c4a7e7?style=flat-square&labelColor=26233a) &nbsp;When multiple compositions are open, pick the active one directly from MFlow's interface.

![presets](https://img.shields.io/badge/Presets_&_profiles-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Save any curve shape as a named preset. Organize presets into profiles and import / export them as JSON to share with your team.

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

**Option A — Standalone installer (Windows)**

Download `MFlow-Setup.exe` from the [Releases page](https://codeberg.org/MaaruAx/MFlow/releases). No Python required.

**Option B — Python**

```bash
python install.py
```

The installer finds your Python, installs dependencies, and places the launcher in Resolve's scripts folder.

Then launch from Resolve based on your license:

| License                                                                                   | Where to launch                                  |
| ----------------------------------------------------------------------------------------- | ------------------------------------------------ |
| ![studio](https://img.shields.io/badge/Studio-eb6f92?style=flat-square&labelColor=26233a) | Any page → `Workspace → Scripts → MFlow`         |
| ![free](https://img.shields.io/badge/Free-9ccfd8?style=flat-square&labelColor=26233a)     | Fusion page only → `Scripts → Comp → MFlow_Free` |

<details>
<summary>

![manual](https://img.shields.io/badge/Manual_install_/_Troubleshooting-f6c177?style=flat-square&labelColor=26233a)

</summary>

<br>

**Studio launcher** — copy `MFlow.lua` + `python_path.txt` to:

| Platform                                                              | Path                                                                                      |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| ![win](https://img.shields.io/badge/Windows-9ccfd8?style=flat-square) | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`             |
| ![mac](https://img.shields.io/badge/macOS-ebbcba?style=flat-square)   | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/` |
| ![lnx](https://img.shields.io/badge/Linux-f6c177?style=flat-square)   | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/`                                   |

**Free launcher** — copy `MFlow_Free.py` + `mflow_path.txt` to `Scripts/Comp/` instead of `Scripts/Utility/`.

To run standalone without Resolve:

```bash
python main.py
```

To uninstall (preserves your settings, presets and profiles):

```bash
python uninstall.py
```

<br>

> **Still stuck? The fastest way to get help is Discord.** Post your error message, your OS, and your Python version and we'll get it fixed.

[![discord](https://img.shields.io/badge/Join_the_Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/dvZ9nvN79Y)

<br>

</details>

---

## ![req](https://img.shields.io/badge/◈_REQUIREMENTS-ebbcba?style=flat-square&labelColor=1a1a2e)

|                                                                                                         |                                                                                                          |
| ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| ![resolve](https://img.shields.io/badge/DaVinci_Resolve_18+-eb6f92?style=flat-square&labelColor=26233a) | Free or Studio — both work                                                                               |
| ![python](https://img.shields.io/badge/Python_3.9+-c4a7e7?style=flat-square&labelColor=26233a)          | Only needed if NOT using the standalone `.exe` — must be from [python.org](https://python.org/downloads) |
| ![pyside](https://img.shields.io/badge/PySide6_≥_6.5-9ccfd8?style=flat-square&labelColor=26233a)        | Installed automatically by `install.py`                                                                  |

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
<sub>Part of the MMarket ecosystem • Created with love for the DaVinci Resolve community.</sub>
<br><br>

</div>
