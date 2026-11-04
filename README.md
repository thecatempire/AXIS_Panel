# AXIS Panel

Embedded rig control panel for AXIS characters (OMNIA 2 and VERSA).
Distributed free with every AXIS model.

## What is this?

The AXIS Panel is a Python script embedded directly inside your Blender character file.
It provides rig controls — IK/FK switching, bone layer visibility, pose tools, and more — from the N-panel in the 3D Viewport.

It is **not** a standalone addon. It comes pre-installed in every AXIS character file and updates itself directly from this repository.

## How to update

Open your AXIS character file in Blender, go to the **AXIS Panel** tab in the N-panel, expand the **Info** section, and click **Check for Updates**. If a new version is available, click **Update Panel** — it downloads and installs automatically.

## Compatible characters

All AXIS-compatible characters are available at:
[superhivemarket.com/creators/thecatempire](https://superhivemarket.com/creators/thecatempire)

## Changelog

### 0.6.6 — 2026-11-04
- New: **Rig Repair**. The panel checks the character for known issues in its corrective shapekeys. If any is found, a red **Repair Rig** button appears under the rig selector; otherwise nothing changes.
- Fixed by Rig Repair: the left thumb correctives (`thumbTwistLeft`, `thumbTipLeft`) reacted to the right thumb.
- Fixed by Rig Repair: `upperArmTwistInRight` and `upperArmTwistOutRight` had their names swapped with respect to the left side. The deformation was already correct; only the names change. If you exported the character or use these shapekey names in other software, re-export after repairing.
- The repair can be undone with Ctrl+Z. Save the file to keep it.
- New: **What's New** button in the Info section, with the changes of the installed version.
- When an update is available, **What's New** lists its changes before you install it.

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

© 2026 Antonio Solano. The panel's code is free software under the GNU General Public License v3 or later (see LICENSE). AXIS characters are sold under their own license terms.
