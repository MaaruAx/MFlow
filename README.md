<div align="center">

# MFlow

### A curve editor for DaVinci Resolve Fusion

*Shape your keyframes. No graph editor required.*

<br>

![Windows](https://img.shields.io/badge/Windows-0078D4?style=flat&logo=windows&logoColor=white)
![macOS](https://img.shields.io/badge/macOS-000000?style=flat&logo=apple&logoColor=white)
![Linux](https://img.shields.io/badge/Linux-FCC624?style=flat&logo=linux&logoColor=black)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat&logo=python&logoColor=white)
![Resolve](https://img.shields.io/badge/DaVinci_Resolve-18+-FF6B00?style=flat)

</div>

---

> **MFlow** is a floating panel that lets you draw bezier curves, dial in physics, and push them into Resolve's splines with one click — without ever opening the graph editor.

---

## ✦ What you get

<table>
<tr>
<td width="50%">

**✦ Six curve modes**
```
Bezier     — free handles + overshoot
Spring     — mass · stiffness · damping
Oscillator — frequency + decay control
Elastic    — amplitude + period
Bounce     — in / out / in-out
Steps      — clean stepped motion
```

</td>
<td width="50%">

**✦ Built for your flow**
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

## ✦ Curve modes in detail

**Bezier** — Pull two handles freely. Enable overshoot to go beyond 0–1. The classic.

**Spring** — Real physics. Set mass, stiffness, damping and initial velocity. MFlow runs the simulation and bakes the result into keyframes so Resolve sees natural, organic motion.

**Oscillator** — Frequency-based oscillation with exponential decay. Good for wobbles, recoils and secondary motion.

**Elastic** — Penner elastic easing with adjustable amplitude and period. Snappier than spring, simpler to control.

**Bounce** — Ball-drop bounce baked as keyframes. In, out, and in-out variants.

**Steps** — Stepped motion with configurable step count and position (snap at start, mid, or end of segment).

---

## ✦ Presets & Profiles

Save any curve as a named preset. Organize presets into profiles — one for motion graphics, one for UI animations, whatever makes sense for your work. Import and export profiles as JSON to share them with your team.

---

## ✦ Installation

**One command:**

```bash
python install.py
```

That's it. The installer finds your Python, installs dependencies, and drops the launcher into Resolve's script folder.

Then in Resolve (Fusion page):

```
Workspace → Scripts → MFlow
```

<details>
<summary>Manual install / troubleshooting</summary>

<br>

Copy `MFlow.lua`, `mflow_path.txt`, and `python_path.txt` into your Resolve Scripts/Utility folder:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\` |
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/` |
| Linux | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/` |

To run without Resolve:
```bash
python main.py
```

</details>

---

## ✦ Requirements

- DaVinci Resolve 18 or newer (Fusion page)
- Python 3.9+ — **not** the Microsoft Store version
- PySide6 — installed automatically by `install.py`

---

## ✦ Credits

Built on top of [FFlow](https://github.com/MisonLarp/Fusion-Flow/) by **Mison** — the open source Bezier curve editor that started it all.

Physics bake (spring, oscillator, elastic) — original implementation.
UI — PySide6 + QWebChannel + HTML/CSS.

---

<div align="center">
<sub>Free and open source. Built for the DaVinci Resolve community.</sub>
</div>