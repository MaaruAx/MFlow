<div align="center">

<br>

# ◈ MFlow

![early-access](https://img.shields.io/badge/⚠_EARLY_ACCESS-ff6b6b?style=for-the-badge&labelColor=1a1a2e)
&nbsp;
![version](https://img.shields.io/badge/version-2.0-c4a7e7?style=for-the-badge&labelColor=1a1a2e)

<br>

**A curve editor for DaVinci Resolve Fusion**

*Shape your keyframes. Apply physics. Stay in Resolve.*

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

> ⚠️ **This is an early access release.** Bugs are expected. Features are being added. Your feedback directly shapes what gets built next — see how to reach us below.

<br>

</div>

---

## ![feat](https://img.shields.io/badge/◈_WHAT_IS_MFLOW-eb6f92?style=flat-square&labelColor=1a1a2e)

**MFlow** is a floating panel that lets you draw bezier curves, dial in physics, and push them directly into Resolve's splines — all from a single click.

<table>
<tr>
<td>

![curves](https://img.shields.io/badge/Six_Curve_Modes-c4a7e7?style=flat-square&labelColor=26233a)

```
Bezier     →  free handles + overshoot
Spring     →  mass · stiffness · damping
Oscillator →  frequency + decay
Elastic    →  amplitude + period
Bounce     →  in / out / in-out
Steps      →  clean stepped motion
```

</td>
<td>

![workflow](https://img.shields.io/badge/Built_For_Your_Flow-9ccfd8?style=flat-square&labelColor=26233a)

```
Launches from Resolve's script menu
Detects your active tool automatically
Updates live as you work
Applies at the playhead position
Detachable floating panels
```

</td>
</tr>
</table>

---

## ![modes](https://img.shields.io/badge/◈_CURVE_MODES-f6c177?style=flat-square&labelColor=1a1a2e)

![bezier](https://img.shields.io/badge/Bezier-ebbcba?style=flat-square&labelColor=26233a) &nbsp;Pull two handles freely. Enable overshoot to go beyond the 0–1 range.

![spring](https://img.shields.io/badge/Spring-eb6f92?style=flat-square&labelColor=26233a) &nbsp;Real physics simulation. Set mass, stiffness, damping and initial velocity. MFlow runs the sim and bakes the result into keyframes so Resolve sees natural, organic motion.

![oscillator](https://img.shields.io/badge/Oscillator-c4a7e7?style=flat-square&labelColor=26233a) &nbsp;Frequency-based oscillation with exponential decay. Wobbles, recoils, secondary motion.

![elastic](https://img.shields.io/badge/Elastic-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Penner elastic easing with adjustable amplitude and period. Snappier than spring, simpler to control.

![bounce](https://img.shields.io/badge/Bounce-f6c177?style=flat-square&labelColor=26233a) &nbsp;Ball-drop physics baked into keyframes. In, out, and in-out.

![steps](https://img.shields.io/badge/Steps-ebbcba?style=flat-square&labelColor=26233a) &nbsp;Stepped motion with configurable step count and snap position — start, mid, or end of segment.

---

## ![presets](https://img.shields.io/badge/◈_PRESETS_&_PROFILES-9ccfd8?style=flat-square&labelColor=1a1a2e)

Save any curve shape as a named preset. Organize presets into profiles — one for motion graphics, one for UI animation, whatever fits your workflow. Import and export profiles as JSON to share with your team.

---

## ![install](https://img.shields.io/badge/◈_INSTALLATION-c4a7e7?style=flat-square&labelColor=1a1a2e)

**One command:**

```bash
python install.py
```

The installer finds your Python, installs dependencies, and drops the launcher into Resolve's scripts folder automatically.

Then in Resolve *(Fusion page)*:

```
Workspace → Scripts → MFlow
```

<details>
<summary>

![manual](https://img.shields.io/badge/Manual_install_/_Troubleshooting-f6c177?style=flat-square&labelColor=26233a)

</summary>

<br>

Copy `MFlow.lua`, `mflow_path.txt`, and `python_path.txt` into your Resolve Scripts/Utility folder:

| Platform | Path |
|---|---|
| ![win](https://img.shields.io/badge/Windows-9ccfd8?style=flat-square) | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\` |
| ![mac](https://img.shields.io/badge/macOS-ebbcba?style=flat-square) | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/` |
| ![lnx](https://img.shields.io/badge/Linux-f6c177?style=flat-square) | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/` |

To run without Resolve open:
```bash
python main.py
```

<br>

![discord](https://img.shields.io/badge/Still_stuck%3F_Join_the_Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)

**→ [discord.gg/YOURLINK](https://discord.gg/YOURLINK)**

Since this is an early access release, Discord is the fastest way to get help. Post your error, your OS, and your Python version and we'll sort it out.

<br>

</details>

---

## ![req](https://img.shields.io/badge/◈_REQUIREMENTS-ebbcba?style=flat-square&labelColor=1a1a2e)

| | |
|---|---|
| ![resolve](https://img.shields.io/badge/DaVinci_Resolve-18+_required-eb6f92?style=flat-square&labelColor=26233a) | Fusion page |
| ![python](https://img.shields.io/badge/Python-3.9+_(not_Microsoft_Store)-c4a7e7?style=flat-square&labelColor=26233a) | [python.org/downloads](https://python.org/downloads) |
| ![pyside](https://img.shields.io/badge/PySide6-auto--installed-9ccfd8?style=flat-square&labelColor=26233a) | Installed by `install.py` |

---

## ![credits](https://img.shields.io/badge/◈_CREDITS-f6c177?style=flat-square&labelColor=1a1a2e)

Built on top of **[FFlow](https://codeberg.org/)** by Mison — the open source Bezier curve editor for Fusion.

Physics bake (spring, oscillator, elastic) — original implementation.
UI — PySide6 + QWebChannel + HTML/CSS.

---

<div align="center">

<br>

![oss](https://img.shields.io/badge/Free_&_Open_Source-26233a?style=for-the-badge)
&nbsp;
[![discord](https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/YOURLINK)

<br>
<sub>Built for the DaVinci Resolve / Fusion community.</sub>

<br>

</div>