<div align="center">

<br>

# ◈ MFlow

![early-access](https://img.shields.io/badge/⚠_EARLY_ACCESS-ff6b6b?style=for-the-badge&labelColor=1a1a2e)
&nbsp;
![version](https://img.shields.io/badge/version-2.0-c4a7e7?style=for-the-badge&labelColor=1a1a2e)
&nbsp;
![free](https://img.shields.io/badge/✓_Works_on_FREE_Resolve-31c48d?style=for-the-badge&labelColor=1a1a2e)

<br>

**A curve editor for DaVinci Resolve Fusion**

*Shape your keyframes. Apply physics. Works on the free version of DaVinci Resolve.*

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

[![downloads](https://img.shields.io/gitea/downloads/release/USER/mflow?gitea_url=https%3A%2F%2Fcodeberg.org&style=flat-square&label=downloads&color=9ccfd8&labelColor=1a1a2e)](https://codeberg.org/USER/mflow/releases)
&nbsp;
[![stars](https://img.shields.io/gitea/stars/USER/mflow?gitea_url=https%3A%2F%2Fcodeberg.org&style=flat-square&label=stars&color=f6c177&labelColor=1a1a2e)](https://codeberg.org/USER/mflow)
&nbsp;
[![issues](https://img.shields.io/gitea/issues/open/USER/mflow?gitea_url=https%3A%2F%2Fcodeberg.org&style=flat-square&label=open%20issues&color=ebbcba&labelColor=1a1a2e)](https://codeberg.org/USER/mflow/issues)
&nbsp;
[![last commit](https://img.shields.io/gitea/last-commit/USER/mflow?gitea_url=https%3A%2F%2Fcodeberg.org&style=flat-square&label=last%20commit&color=c4a7e7&labelColor=1a1a2e)](https://codeberg.org/USER/mflow/commits/branch/main)

<br>

> ⚠️ **Early access release.** Bugs are expected and features are actively being added. Your feedback directly shapes what gets built next — see how to reach us below.

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
Bezier      →  free handles + overshoot
Spring      →  mass · stiffness · damping
Elastic     →  amplitude + period
Overframe   →  bezier with mid control points
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

![bezier](https://img.shields.io/badge/Bezier-9ccfd8?style=flat-square&labelColor=26233a) &nbsp;Pull two handles freely across the curve. Enable overshoot to push beyond the 0–1 range and get natural overshoots and anticipations.

![spring](https://img.shields.io/badge/Spring-f6c177?style=flat-square&labelColor=26233a) &nbsp;A real damped harmonic oscillator runs under the hood. Set mass, stiffness, damping and initial velocity — MFlow integrates the physics frame by frame and bakes the result directly into your spline keyframes.

![elastic](https://img.shields.io/badge/Elastic-eb6f92?style=flat-square&labelColor=26233a) &nbsp;Penner elastic easing with adjustable amplitude and period. Snappier and more predictable than Spring, great for UI and graphic elements.

![overframe](https://img.shields.io/badge/Overframe-c4a7e7?style=flat-square&labelColor=26233a) &nbsp;Adds intermediate keyframes between your two main keys and lets you control each sub-segment independently. You get a multi-point bezier — complex curves that would normally take many manual keyframes, built in seconds.

---

## ![presets](https://img.shields.io/badge/◈_PRESETS_&_PROFILES-9ccfd8?style=flat-square&labelColor=1a1a2e)

Save any curve shape as a named preset. Organize presets into profiles — one for motion graphics, one for UI animation, whatever fits your workflow. Import and export profiles as JSON to share with your team.

---

## ![install](https://img.shields.io/badge/◈_INSTALLATION-c4a7e7?style=flat-square&labelColor=1a1a2e)

**One command:**

```bash
python install.py
```

The installer finds your Python, installs dependencies, and places the launcher in Resolve's scripts folder automatically.

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

> **Still stuck? The fastest way to get help is Discord.** Since this is an early access release, many issues are already known and solved there. Post your error message, your OS, and your Python version and we'll get it fixed.

[![discord](https://img.shields.io/badge/Join_the_Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/YOURLINK)

<br>

</details>

---

## ![req](https://img.shields.io/badge/◈_REQUIREMENTS-ebbcba?style=flat-square&labelColor=1a1a2e)

| | |
|---|---|
| ![resolve](https://img.shields.io/badge/DaVinci_Resolve_18+-eb6f92?style=flat-square&labelColor=26233a) | Free or Studio — both work |
| ![python](https://img.shields.io/badge/Python_3.9+-c4a7e7?style=flat-square&labelColor=26233a) | **Must be the `.exe` installer from [python.org](https://python.org/downloads)** |
| ![pyside](https://img.shields.io/badge/PySide6-9ccfd8?style=flat-square&labelColor=26233a) | Installed automatically by `install.py` |

> ⚠️ **Python from the Microsoft Store will not work.** It is a restricted stub that cannot load the DaVinci Resolve scripting modules. Download the standard installer from **[python.org/downloads](https://python.org/downloads)** and make sure to check *"Add Python to PATH"* during setup.

---

## ![credits](https://img.shields.io/badge/◈_CREDITS-f6c177?style=flat-square&labelColor=1a1a2e)

Built on top of **[FFlow](https://codeberg.org/)** by Mison — the open source Bezier curve editor for Fusion.

Physics bake (spring, elastic, overframe) — original implementation.
UI — PySide6 + QWebChannel + HTML/CSS.

---

<div align="center">

<br>

![oss](https://img.shields.io/badge/Free_&_Open_Source-26233a?style=for-the-badge)
&nbsp;
[![discord](https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/YOURLINK)
&nbsp;
[![releases](https://img.shields.io/badge/Releases-eb6f92?style=for-the-badge)](https://codeberg.org/USER/mflow/releases)

<br>
<sub>Built for the DaVinci Resolve / Fusion community.</sub>
<br><br>

</div>