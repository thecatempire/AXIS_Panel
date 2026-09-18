# AXIS Panel

Embedded rig control panels for AXIS characters (OMNIA 2, VERSA and VERSA V2).
Distributed free with every AXIS model.

## What is this?

The AXIS Panel is a Python script embedded directly inside your Blender character file.
It provides rig controls — IK/FK switching, bone layer visibility, pose tools, and more — from the N-panel in the 3D Viewport.

It is **not** a standalone addon. It comes pre-installed in every AXIS character file and updates itself directly from this repository.

## Two panels

- **AXIS Panel** (`AXIS_Panel.py`) — the panel of OMNIA 2 and VERSA characters, in the **AXIS Panel** tab.
- **AXIS Rig Panel** (`AXIS_Rig_Panel.py`) — the panel of VERSA V2 characters, in the **AXIS Rig** tab. Supported from Blender 4.5 LTS; works from Blender 4.0.

Each panel updates only from its own files, so a character always receives updates for the panel it was delivered with.

## How to update

Open your AXIS character file in Blender, go to the panel's tab in the N-panel (**AXIS Panel** or **AXIS Rig**), expand the **Info** section, and click **Check for Updates**. If a new version is available, click **Update Panel** — it downloads and installs automatically.

## Compatible characters

All AXIS-compatible characters are available at:
[superhivemarket.com/creators/thecatempire](https://superhivemarket.com/creators/thecatempire)

## Changelog — AXIS Rig Panel

### 2.0.1 — 2026-09-18
- Works from Blender 4.0: bone selection, IK control visibility and the Face Widget layers on Blender 4.x.
- Fixed: Fingers FK → IK.
- Licensed under the GNU GPL v3 or later.

### 2.0.0 — 2026-09-17
- First version, for VERSA V2 characters.

## Changelog — AXIS Panel

### 0.6.5 — 2026-09-10
- Fixed: pressing Update Panel could crash Blender. The new panel now registers once the update has finished.

### 0.6.4 — 2026-09-10
- Security: the updater now verifies GitHub's certificate before downloading and installing a new panel.

### 0.6.3 — 2026-04-06
- The Support button now writes to contact@axisproject.co.

### 0.6.2 — 2026-03-25
- The Documentation button now opens axisproject.co/documentation.

### 0.6.1 — 2026-03-25
- First version published in this repository.

---

© 2026 Antonio Solano. The panels' code is free software under the GNU General Public License v3 or later (see LICENSE). AXIS characters are sold under their own license terms.
