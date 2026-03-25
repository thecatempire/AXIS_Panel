# SPDX-License-Identifier: LicenseRef-AXIS-EULA
# Copyright (c) 2026 Antonio Solano — All rights reserved.
# Project: AXIS Panel
# Module: AXIS_Panel.py
# Documentation: https://axisproject.co/documentation


__author__  = "Antonio Solano"
__license__ = "LicenseRef-AXIS-EULA"
PANEL_VERSION = (0, 6, 3)
PANEL_VERSION_STR = ".".join(map(str, PANEL_VERSION))


import bpy, threading, json, ssl
from urllib import request as _urllib_request

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_VERSION_URL   = "https://raw.githubusercontent.com/thecatempire/AXIS_Panel/main/version.json"
_PANEL_RAW_URL = "https://raw.githubusercontent.com/thecatempire/AXIS_Panel/main/AXIS_Panel.py"

_update_state = {
    "status": "idle",   # idle | checking | available | up_to_date | error
    "remote_version": None,
}

# -----------------------------
# Constants
# -----------------------------
LEGEND_MAIN = "Legend"
EXCLUDED_NAMES = {"Dev", "MCH", "DEF", "ORG", "Hidden", "FaceDev"}

# -----------------------------
# Utilities
# -----------------------------
def get_bone_collections(armature):
    colls = getattr(armature, "bone_collections", None) or getattr(armature, "collections", None)
    if colls is not None:
        return [c for c in colls if all(x not in c.name for x in EXCLUDED_NAMES)]
    return []


def _get_widget_for_rig(main_rig):
    widgets = [
        obj for obj in bpy.data.objects
        if obj.type == 'ARMATURE' and obj.data.get("widget_id")
    ]
    if not widgets:
        return None
    if main_rig:
        for obj in widgets:
            con = obj.constraints.get("widgetFollowHead")
            if con and getattr(con, "target", None) is main_rig:
                return obj
    return widgets[0] if len(widgets) == 1 else None



# -----------------------------
# Properties
# -----------------------------
class AXIS_PanelProps(bpy.types.PropertyGroup):
    expand_widget:         bpy.props.BoolProperty(name="Show Facial Widget",       default=False)
    expand_rig:            bpy.props.BoolProperty(name="Show Rig Layers",           default=False)
    expand_performance:    bpy.props.BoolProperty(name="Show Performance Tools",    default=False)
    expand_pose_tools:     bpy.props.BoolProperty(name="Show Pose Tools",           default=False)
    expand_adv_pose_tools: bpy.props.BoolProperty(name="Show Advanced Pose Tools",  default=False)
    expand_info:           bpy.props.BoolProperty(name="Show Info",                 default=False)

# -----------------------------
# Operators
# -----------------------------
class AXIS_OT_ToggleSimplify(bpy.types.Operator):
    bl_idname = "axis.toggle_simplify"
    bl_label = "Toggle Simplify"
    bl_description = "Enable or disable the Simplify option"

    def execute(self, context):
        scene = context.scene
        scene.render.use_simplify = not scene.render.use_simplify
        state = "ON" if scene.render.use_simplify else "OFF"
        self.report({'INFO'}, f"Simplify {state}")
        return {'FINISHED'}


class AXIS_OT_SetLegend(bpy.types.Operator):
    bl_idname = "axis_widget.toggle_legend"
    bl_label = "Toggle Legend"
    value: bpy.props.BoolProperty()

    def execute(self, context):
        widget_obj = next(
            (obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.data.get("widget_id") and "widget" in obj.name.lower()),
            None,
        )
        if not widget_obj:
            return {'CANCELLED'}
        for coll in get_bone_collections(widget_obj.data):
            if coll.name == LEGEND_MAIN:
                coll.is_visible = self.value
        return {'FINISHED'}

# ------------------------------------------------------------
# IK/FK quick toggles (standalone)
# ------------------------------------------------------------
def _panel_is_axis_rig(obj):
    if not (obj and getattr(obj, "type", "") == 'ARMATURE'):
        return False
    try:
        return any(c.name == "Dev" for c in obj.data.collections)
    except Exception:
        return False

def _panel_get_main_rig(context):
    rig = getattr(context.scene, "axis_panel_rig", None)
    return rig if _panel_is_axis_rig(rig) else None

def _panel_set_bone_prop_if_exists(rig, bone_name: str, prop: str, value: float):
    pb = rig.pose.bones.get(bone_name) if (rig and rig.pose) else None
    if pb:
        try:
            pb[prop] = float(value)
        except Exception:
            pass

def _panel_get_ikfk_val(rig, bone_name: str, default=0.0):
    pb = rig.pose.bones.get(bone_name) if (rig and rig.pose) else None
    if pb and "IK_FK" in pb.keys():
        try:
            return float(pb["IK_FK"])
        except Exception:
            return float(default)
    return float(default)

def _panel_all_limbs_ik(rig, include_legs: bool):
    names = ["upper_arm_parent.L", "upper_arm_parent.R"]
    if include_legs:
        names += ["thigh_parent.L", "thigh_parent.R"]
    return all(_panel_get_ikfk_val(rig, n, 0.0) >= 0.5 for n in names)

def _panel_has_bone(rig, name: str) -> bool:
    return bool(rig and rig.pose and rig.pose.bones.get(name))

def _panel_has_legs(rig) -> bool:
    if not (_panel_has_bone(rig, "thigh_parent.L") and _panel_has_bone(rig, "thigh_parent.R")):
        return False
    colls = getattr(rig.data, "bone_collections", None) or getattr(rig.data, "collections", None) or []
    return any("Leg" in c.name for c in colls)

def _panel_refresh(context, rig=None):
    try:
        if rig:
            try: rig.update_tag()
            except Exception: pass
            try: rig.data.update_tag()
            except Exception: pass
        context.view_layer.update()
        context.evaluated_depsgraph_get().update()
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type in {'VIEW_3D','DOPESHEET_EDITOR','GRAPH_EDITOR'}:
                    area.tag_redraw()
    except Exception:
        pass


def _panel_get_rig_id(rig):
    for getter in (lambda: rig.data.get("rig_id"), lambda: rig.get("rig_id")):
        try:
            v = getter()
            if isinstance(v, (str, bytes)) and len(str(v)) > 0:
                return str(v)
        except Exception:
            pass
    return None

def _panel_activate_pose(context, rig):
    prev_active = context.view_layer.objects.active
    prev_mode = context.mode
    for o in list(context.selected_objects):
        try: o.select_set(False)
        except Exception: pass
    rig.select_set(True)
    context.view_layer.objects.active = rig
    if rig.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE', toggle=False)
    return prev_active, prev_mode

def _panel_restore_active(prev_active, prev_mode):
    try:
        if prev_active and prev_active.name in bpy.context.view_layer.objects:
            bpy.context.view_layer.objects.active = prev_active
            prev_active.select_set(True)
    except Exception:
        pass
    try:
        if prev_mode and bpy.context.mode != prev_mode:
            bpy.ops.object.mode_set(mode=prev_mode, toggle=False)
    except Exception:
        pass

_PANEL_SYNC_LOCK = {"active": False}

def _panel_set_scene_prop_silent(sc, name, value):
    _PANEL_SYNC_LOCK["active"] = True
    try:
        if hasattr(sc, name):
            setattr(sc, name, float(value))
    finally:
        _PANEL_SYNC_LOCK["active"] = False

def _panel_sync_ikfk_from_rig(context, rig):
    if not (rig and rig.pose):
        return
    sc = context.scene
    pb = rig.pose.bones
    def _v(bn, key, default=0.0):
        p = pb.get(bn)
        if p and key in p.keys():
            try: return float(p[key])
            except Exception: pass
        return float(default)
    _panel_set_scene_prop_silent(sc, "axis_panel_arm_ikfk_L",      _v("upper_arm_parent.L", "IK_FK"))
    _panel_set_scene_prop_silent(sc, "axis_panel_arm_ikfk_R",      _v("upper_arm_parent.R", "IK_FK"))
    _panel_set_scene_prop_silent(sc, "axis_panel_leg_ikfk_L",      _v("thigh_parent.L",     "IK_FK"))
    _panel_set_scene_prop_silent(sc, "axis_panel_leg_ikfk_R",      _v("thigh_parent.R",     "IK_FK"))
    _panel_set_scene_prop_silent(sc, "axis_panel_fingers_fkik_L",  _v("thumb.01_ik.L",      "FK_IK"))
    _panel_set_scene_prop_silent(sc, "axis_panel_fingers_fkik_R",  _v("thumb.01_ik.R",      "FK_IK"))

def _panel_make_arm_update(side):
    def _fn(self, context):
        if _PANEL_SYNC_LOCK.get("active"): return
        rig = _panel_get_main_rig(context)
        if not rig: return
        v = float(getattr(context.scene, f"axis_panel_arm_ikfk_{side}", 1.0))
        _panel_set_bone_prop_if_exists(rig, f"upper_arm_parent.{side}", "IK_FK", v)
        _panel_refresh(context, rig)
    return _fn

def _panel_make_leg_update(side):
    def _fn(self, context):
        if _PANEL_SYNC_LOCK.get("active"): return
        rig = _panel_get_main_rig(context)
        if not rig: return
        v = float(getattr(context.scene, f"axis_panel_leg_ikfk_{side}", 1.0))
        _panel_set_bone_prop_if_exists(rig, f"thigh_parent.{side}", "IK_FK", v)
        _panel_refresh(context, rig)
    return _fn

def _panel_make_fingers_update(side):
    bones = (
        f"thumb.01_ik.{side}", f"f_index.01_ik.{side}", f"f_middle.01_ik.{side}",
        f"f_ring.01_ik.{side}", f"f_pinky.01_ik.{side}",
    )
    def _fn(self, context):
        if _PANEL_SYNC_LOCK.get("active"): return
        rig = _panel_get_main_rig(context)
        if not rig: return
        v = float(getattr(context.scene, f"axis_panel_fingers_fkik_{side}", 0.0))
        for b in bones:
            _panel_set_bone_prop_if_exists(rig, b, "FK_IK", v)
        _panel_refresh(context, rig)
    return _fn


class AXIS_OT_panel_toggle_ikfk_limbs_global(bpy.types.Operator):
    bl_idname = "axis_panel.toggle_ikfk_limbs_global"
    bl_label  = "Global FK (Arms & Legs)"
    bl_description = "Toggle IK/FK for arms and, if available, for legs"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        if not rig:
            self.report({'ERROR'}, "Select a rig.")
            return {'CANCELLED'}
        has_legs = _panel_has_legs(rig)
        is_all_ik = _panel_all_limbs_ik(rig, include_legs=has_legs)
        new_val = 0.0 if is_all_ik else 1.0
        for bn in ("upper_arm_parent.L", "upper_arm_parent.R"):
            _panel_set_bone_prop_if_exists(rig, bn, "IK_FK", new_val)
        if has_legs:
            for bn in ("thigh_parent.L", "thigh_parent.R"):
                _panel_set_bone_prop_if_exists(rig, bn, "IK_FK", new_val)
        _panel_refresh(context, rig)
        _panel_sync_ikfk_from_rig(context, rig)
        self.report({'INFO'}, f"Toggled limbs IK/FK → {'FK' if new_val == 0.0 else 'IK'}")
        return {'FINISHED'}


class AXIS_OT_panel_toggle_fkik_fingers_global(bpy.types.Operator):
    bl_idname = "axis_panel.toggle_fkik_fingers_global"
    bl_label  = "Global Fingers IK"
    bl_description = "Toggle FK/IK for all fingers in both hands"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        if not rig:
            self.report({'ERROR'}, "Select a rig.")
            return {'CANCELLED'}
        def _get_fkik(side):
            pb = rig.pose.bones.get(f"thumb.01_ik.{side}") if (rig and rig.pose) else None
            return float(pb["FK_IK"]) if (pb and "FK_IK" in pb.keys()) else 0.0
        both_ik = (_get_fkik('L') >= 0.5 and _get_fkik('R') >= 0.5)
        new_val = 0.0 if both_ik else 1.0
        for side in ('L','R'):
            for b in (f"thumb.01_ik.{side}", f"f_index.01_ik.{side}", f"f_middle.01_ik.{side}",
                      f"f_ring.01_ik.{side}", f"f_pinky.01_ik.{side}"):
                _panel_set_bone_prop_if_exists(rig, b, "FK_IK", new_val)
        _panel_refresh(context, rig)
        _panel_sync_ikfk_from_rig(context, rig)
        self.report({'INFO'}, f"Toggled Fingers FK/IK → {'FK' if new_val == 0.0 else 'IK'}")
        return {'FINISHED'}


# ------------------------------------------------------------
# Snap FK/IK operators
# ------------------------------------------------------------
import json as _json

def _panel_snap_limb(rig, rid, side, limb, direction):
    if limb == 'arm':
        fk   = [f"upper_arm_fk.{side}", f"forearm_fk.{side}", f"hand_fk.{side}"]
        ik   = [f"upper_arm_ik.{side}", f"MCH-forearm_ik.{side}", f"MCH-upper_arm_ik_target.{side}"]
        ctrl = [f"upper_arm_ik.{side}", f"upper_arm_ik_target.{side}", f"hand_ik.{side}"]
        prop_bone = f"upper_arm_parent.{side}"
    else:
        fk   = [f"thigh_fk.{side}", f"shin_fk.{side}", f"foot_fk.{side}"]
        ik   = [f"thigh_ik.{side}", f"MCH-shin_ik.{side}", f"MCH-thigh_ik_target.{side}"]
        ctrl = [f"thigh_ik.{side}", f"thigh_ik_target.{side}", f"foot_ik.{side}"]
        prop_bone = f"thigh_parent.{side}"
    if direction == 'FK2IK':
        getattr(bpy.ops.pose, f"rigify_generic_snap_{rid}")(
            output_bones=_json.dumps(fk),
            input_bones=_json.dumps(ik),
            ctrl_bones=_json.dumps(ctrl),
        )
    else:
        getattr(bpy.ops.pose, f"rigify_limb_ik2fk_{rid}")(
            prop_bone=prop_bone,
            fk_bones=_json.dumps(fk),
            ik_bones=_json.dumps(ik),
            ctrl_bones=_json.dumps(ctrl),
            tail_bones=_json.dumps([]),
            extra_ctrls=_json.dumps([]),
        )


def _panel_snap_fingers(rig, rid, side, direction):
    fingers = ('thumb', 'f_index', 'f_middle', 'f_ring', 'f_pinky')
    for f in fingers:
        ik_ctrl = f"{f}.01_ik.{side}"
        if not (rig.pose and rig.pose.bones.get(ik_ctrl)):
            continue
        fk_master = f"{f}.01_master.{side}"
        fk_chain  = _json.dumps([f"{f}.01.{side}", f"{f}.02.{side}", f"{f}.03.{side}", f"{f}.01.{side}.001"])
        ik_chain  = _json.dumps([f"ORG-{f}.01.{side}", f"ORG-{f}.02.{side}", f"ORG-{f}.03.{side}"])
        try:
            if direction == 'FK2IK':
                getattr(bpy.ops.pose, f"rigify_finger_fk2ik_{rid}")(
                    fk_master=fk_master, fk_chain=fk_chain, ik_chain=ik_chain,
                    ik_control=ik_ctrl, constraint_bone=f"ORG-{f}.03.{side}", axis='+X',
                )
            else:
                getattr(bpy.ops.pose, f"rigify_generic_snap_{rid}")(
                    output_bones=_json.dumps([ik_ctrl]),
                    input_bones=_json.dumps([f"{f}.01.{side}.001"]),
                    ctrl_bones=_json.dumps([fk_master, f"{f}.01.{side}", f"{f}.02.{side}", f"{f}.03.{side}", f"{f}.01.{side}.001"]),
                    locks=(False, True, True), tooltip='IK to FK',
                )
        except Exception:
            pass


class AXIS_OT_panel_snap_fingers(bpy.types.Operator):
    bl_idname  = "axis_panel.snap_fingers"
    bl_label   = "Snap Fingers"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Snap FK/IK for all fingers on the selected hand"

    side:      bpy.props.StringProperty(default='L', options={'HIDDEN'})
    direction: bpy.props.StringProperty(default='FK2IK', options={'HIDDEN'})

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        rid = _panel_get_rig_id(rig)
        if not (rig and rid):
            self.report({'ERROR'}, "No valid AXIS rig found.")
            return {'CANCELLED'}
        prev_active, prev_mode = _panel_activate_pose(context, rig)
        try:
            _panel_snap_fingers(rig, rid, self.side, self.direction)
            _panel_refresh(context, rig)
            _panel_sync_ikfk_from_rig(context, rig)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Finger snap error: {e}")
            return {'CANCELLED'}
        finally:
            _panel_restore_active(prev_active, prev_mode)


class AXIS_OT_panel_snap(bpy.types.Operator):
    bl_idname  = "axis_panel.snap"
    bl_label   = "Snap"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Snap FK/IK for the selected limb"

    side:      bpy.props.StringProperty(options={'HIDDEN'})
    limb:      bpy.props.StringProperty(options={'HIDDEN'})
    direction: bpy.props.StringProperty(options={'HIDDEN'})

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        rid = _panel_get_rig_id(rig)
        if not (rig and rid):
            self.report({'ERROR'}, "No valid AXIS rig found.")
            return {'CANCELLED'}
        prev_active, prev_mode = _panel_activate_pose(context, rig)
        try:
            _panel_snap_limb(rig, rid, self.side, self.limb, self.direction)
            _panel_refresh(context, rig)
            _panel_sync_ikfk_from_rig(context, rig)
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Snap error: {e}")
            return {'CANCELLED'}
        finally:
            _panel_restore_active(prev_active, prev_mode)


class _AXIS_OT_panel_snap_global_base(bpy.types.Operator):
    bl_options = {'REGISTER', 'UNDO'}
    _direction = 'FK2IK'

    @classmethod
    def poll(cls, context):
        return _panel_get_main_rig(context) is not None

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        rid = _panel_get_rig_id(rig)
        if not (rig and rid):
            self.report({'ERROR'}, "No valid AXIS rig found.")
            return {'CANCELLED'}
        has_legs = _panel_has_legs(rig)
        limbs = [('arm', 'L'), ('arm', 'R')]
        if has_legs:
            limbs += [('leg', 'L'), ('leg', 'R')]
        prev_active, prev_mode = _panel_activate_pose(context, rig)
        errors = []
        try:
            for limb, side in limbs:
                try:
                    _panel_snap_limb(rig, rid, side, limb, self._direction)
                except Exception as e:
                    errors.append(str(e))
        finally:
            _panel_restore_active(prev_active, prev_mode)
        _panel_refresh(context, rig)
        _panel_sync_ikfk_from_rig(context, rig)
        if errors:
            self.report({'WARNING'}, f"Some snaps failed: {errors[0]}")
        return {'FINISHED'}


class AXIS_OT_panel_snap_global_fk2ik(_AXIS_OT_panel_snap_global_base):
    bl_idname   = "axis_panel.snap_global_fk2ik"
    bl_label    = "Global FK → IK"
    bl_description = "Snap all limbs from FK to IK"
    _direction  = 'FK2IK'


class AXIS_OT_panel_snap_global_ik2fk(_AXIS_OT_panel_snap_global_base):
    bl_idname   = "axis_panel.snap_global_ik2fk"
    bl_label    = "Global IK → FK"
    bl_description = "Snap all limbs from IK to FK"
    _direction  = 'IK2FK'


class AXIS_OT_panel_reset_pose(bpy.types.Operator):
    bl_idname  = "axis_panel.reset_pose"
    bl_label   = "Reset Pose"
    bl_description = "Reset all pose bone transforms to rest on the active rig"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        if not (rig and rig.type == 'ARMATURE'):
            self.report({'ERROR'}, "No armature found.")
            return {'CANCELLED'}

        prev_active = context.view_layer.objects.active
        try:
            rig.hide_set(False)
        except Exception:
            pass
        context.view_layer.objects.active = rig

        if context.mode != 'POSE':
            bpy.ops.object.mode_set(mode='POSE')

        bpy.ops.pose.select_all(action='SELECT')
        for pb in rig.pose.bones:
            pb.location = (0.0, 0.0, 0.0)
            pb.scale    = (1.0, 1.0, 1.0)
            if pb.rotation_mode == 'QUATERNION':
                pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            elif pb.rotation_mode == 'AXIS_ANGLE':
                pb.rotation_axis_angle = (0.0, 1.0, 0.0, 0.0)
            else:
                pb.rotation_euler = (0.0, 0.0, 0.0)

        bpy.ops.object.mode_set(mode='OBJECT')

        if prev_active and prev_active.name in context.view_layer.objects:
            context.view_layer.objects.active = prev_active
        try:
            context.view_layer.update()
        except Exception:
            pass

        self.report({'INFO'}, "Pose reset.")
        return {'FINISHED'}


def _panel_limits_active(rig):
    if not (rig and rig.pose):
        return False
    for pb in rig.pose.bones:
        for con in pb.constraints:
            if con.name.startswith("Limit") and not con.mute:
                return True
    return False


class AXIS_OT_panel_toggle_limits(bpy.types.Operator):
    bl_idname  = "axis_panel.toggle_limits"
    bl_label   = "Toggle Limits"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "Mute or unmute all Limit bone constraints (Limit Rotation, Limit Location, etc.) on the active rig"

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        if not rig:
            return {'CANCELLED'}
        new_mute = _panel_limits_active(rig)
        for pb in rig.pose.bones:
            for con in pb.constraints:
                if con.name.startswith("Limit"):
                    con.mute = new_mute
        state = "disabled" if new_mute else "enabled"
        self.report({'INFO'}, f"Limit constraints {state}.")
        return {'FINISHED'}


class AXIS_OT_panel_toggle_mode(bpy.types.Operator):
    bl_idname  = "axis_panel.toggle_mode"
    bl_label   = "Toggle Pose/Object"
    bl_description = "Switch between Object and Pose mode on the active rig"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        if not (rig and rig.type == 'ARMATURE'):
            self.report({'ERROR'}, "No armature found.")
            return {'CANCELLED'}
        try:
            rig.hide_set(False)
        except Exception:
            pass
        context.view_layer.objects.active = rig
        rig.select_set(True)
        target = 'OBJECT' if context.mode == 'POSE' else 'POSE'
        bpy.ops.object.mode_set(mode=target)
        return {'FINISHED'}


class AXIS_OT_panel_copy_pose(bpy.types.Operator):
    bl_idname  = "axis_panel.copy_pose"
    bl_label   = "Copy Pose"
    bl_description = "Copy the current pose of selected bones to clipboard"
    bl_options = {'REGISTER'}

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        if not (rig and rig.type == 'ARMATURE'):
            self.report({'ERROR'}, "No armature found.")
            return {'CANCELLED'}
        prev_active, prev_mode = _panel_activate_pose(context, rig)
        try:
            bpy.ops.pose.copy()
        finally:
            _panel_restore_active(prev_active, prev_mode)
        self.report({'INFO'}, "Pose copied.")
        return {'FINISHED'}


class AXIS_OT_panel_paste_pose(bpy.types.Operator):
    bl_idname  = "axis_panel.paste_pose"
    bl_label   = "Paste Pose"
    bl_description = "Paste the copied pose onto selected bones (optionally flipped)"
    bl_options = {'REGISTER', 'UNDO'}

    flipped: bpy.props.BoolProperty(name="Flipped", default=False, options={'HIDDEN'})

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        if not (rig and rig.type == 'ARMATURE'):
            self.report({'ERROR'}, "No armature found.")
            return {'CANCELLED'}
        prev_active, prev_mode = _panel_activate_pose(context, rig)
        try:
            bpy.ops.pose.paste(flipped=self.flipped, selected_mask=True)
        finally:
            _panel_restore_active(prev_active, prev_mode)
        label = "Pose pasted (flipped)." if self.flipped else "Pose pasted."
        self.report({'INFO'}, label)
        return {'FINISHED'}


def _panel_apply_mirrored(pb_dst, loc, mode, quat, euler, aa, scale):
    import mathutils
    mirrored_loc = loc.copy()
    mirrored_loc.x = -mirrored_loc.x
    pb_dst.location = mirrored_loc

    if pb_dst.rotation_mode != mode:
        pb_dst.rotation_mode = mode

    if mode == 'QUATERNION':
        pb_dst.rotation_quaternion = mathutils.Quaternion((quat.w, quat.x, -quat.y, -quat.z))
    elif mode == 'AXIS_ANGLE':
        pb_dst.rotation_axis_angle = (aa[0], aa[1], -aa[2], -aa[3])
    else:
        e = euler.copy()
        e.y = -e.y
        e.z = -e.z
        pb_dst.rotation_euler = e

    pb_dst.scale = scale.copy()


class AXIS_OT_panel_side_mirror(bpy.types.Operator):
    bl_idname  = "axis_panel.side_mirror"
    bl_label   = "Flip/Mirror Pose"
    bl_options = {'REGISTER', 'UNDO'}

    src:  bpy.props.StringProperty(default='L', options={'HIDDEN'})
    mode: bpy.props.StringProperty(default='MIRROR', options={'HIDDEN'})

    def execute(self, context):
        rig = _panel_get_main_rig(context)
        if not (rig and rig.type == 'ARMATURE'):
            self.report({'ERROR'}, "No armature found.")
            return {'CANCELLED'}
        prev_active, prev_mode = _panel_activate_pose(context, rig)
        try:
            if self.mode == 'FLIP':
                snapshot = {
                    pb.name: (
                        pb.location.copy(),
                        pb.rotation_mode,
                        pb.rotation_quaternion.copy(),
                        pb.rotation_euler.copy(),
                        tuple(pb.rotation_axis_angle),
                        pb.scale.copy(),
                    )
                    for pb in rig.pose.bones
                }
                for name_L, data in snapshot.items():
                    if not name_L.endswith('.L'):
                        continue
                    name_R = name_L[:-2] + '.R'
                    if name_R not in snapshot:
                        continue
                    pb_L = rig.pose.bones.get(name_L)
                    pb_R = rig.pose.bones.get(name_R)
                    if not (pb_L and pb_R):
                        continue
                    _panel_apply_mirrored(pb_R, *snapshot[name_L])
                    _panel_apply_mirrored(pb_L, *snapshot[name_R])
                self.report({'INFO'}, "Pose flipped (L \u2194 R).")

            else:  # MIRROR
                src = self.src
                dst = 'R' if src == 'L' else 'L'
                for pb_src in rig.pose.bones:
                    if not pb_src.name.endswith('.' + src):
                        continue
                    base = pb_src.name[:-(len(src) + 1)]
                    pb_dst = rig.pose.bones.get(f"{base}.{dst}")
                    if not pb_dst:
                        continue
                    _panel_apply_mirrored(
                        pb_dst,
                        pb_src.location,
                        pb_src.rotation_mode,
                        pb_src.rotation_quaternion,
                        pb_src.rotation_euler,
                        tuple(pb_src.rotation_axis_angle),
                        pb_src.scale,
                    )
                self.report({'INFO'}, f"Mirrored {src} \u2192 {dst}.")

            _panel_refresh(context, rig)
        finally:
            _panel_restore_active(prev_active, prev_mode)
        return {'FINISHED'}


# -----------------------------
# Panel
# -----------------------------
class AXIS_PT_MainPanel(bpy.types.Panel):
    bl_label = "AXIS Panel"
    bl_idname = "AXIS_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "AXIS Panel"

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'}

    def draw(self, context):
        layout = self.layout
        sc    = context.scene
        props = sc.axis_panel_props

        box = layout.box()
        row = box.row()
        row.prop(props, "expand_performance", text="", icon="TRIA_DOWN" if props.expand_performance else "TRIA_RIGHT", emboss=False)
        row.label(text="Performance Tools", icon="MEMORY")
        if props.expand_performance:
            row = box.row()
            row.operator("axis.toggle_simplify", text="Simplify", icon="CHECKBOX_HLT" if sc.render.use_simplify else "CHECKBOX_DEHLT")
            sub = box.column(align=True)
            sub.enabled = sc.render.use_simplify
            sub.prop(sc.render, "simplify_subdivision",     text="Max Subdivision")
            sub.prop(sc.render, "simplify_child_particles", text="Child Particles", slider=True)
            note = box.column(align=True)
            note.scale_y = 0.8
            note.label(text="Viewport only. Render always", icon="INFO")
            note.label(text="uses full quality.", icon="BLANK1")

        if not _panel_is_axis_rig(getattr(sc, "axis_panel_rig", None)):
            for o in context.view_layer.objects:
                if _panel_is_axis_rig(o):
                    try:
                        sc.axis_panel_rig = o
                    except Exception:
                        pass
                    break

        sel_box = layout.box()
        sel_box.label(text="AXIS Rig", icon='ARMATURE_DATA')
        row = sel_box.row(align=True)
        row.prop(sc, "axis_panel_rig", text="")

        rig_obj = _panel_get_main_rig(context)

        if not rig_obj:
            row = sel_box.row()
            row.alert = True
            row.label(text="No AXIS rig assigned.", icon='ERROR')
            _panel_draw_info_block(layout, context)
            return

        widget_obj = _get_widget_for_rig(rig_obj)
        if widget_obj and widget_obj.type == "ARMATURE":
            box = layout.box()
            row = box.row()
            row.prop(props, "expand_widget", text="", icon="TRIA_DOWN" if props.expand_widget else "TRIA_RIGHT", emboss=False)
            row.label(text="Facial Widget Layers", icon="SHAPEKEY_DATA")
            if props.expand_widget:
                arm = widget_obj.data
                bone_colls = get_bone_collections(arm)

                legend = next((c for c in bone_colls if c.name == LEGEND_MAIN), None)
                if legend:
                    row = box.row()
                    row.prop(legend, "is_visible", text="Show/Hide Legend", toggle=True)

                visible = [c for c in bone_colls if c.name != LEGEND_MAIN]
                n = len(visible)
                for i in range(0, n, 2):
                    row = box.row(align=True)
                    row.prop(visible[i], "is_visible", text=visible[i].name, toggle=True)
                    if i + 1 < n:
                        row.separator(factor=1.2)
                        row.prop(visible[i + 1], "is_visible", text=visible[i + 1].name, toggle=True)

                constr = widget_obj.constraints.get("widgetFollowHead")
                if constr and constr.type == 'CHILD_OF':
                    cbox = box.box()
                    cbox.label(text="Widget Options", icon="CONSTRAINT_BONE")
                    cbox.prop(constr, "influence", text="Follow Head", slider=True)

        if rig_obj and rig_obj.type == "ARMATURE":
            box = layout.box()
            row = box.row()
            row.prop(props, "expand_rig", text="", icon="TRIA_DOWN" if props.expand_rig else "TRIA_RIGHT", emboss=False)
            row.label(text="Main Rig Layers", icon="ARMATURE_DATA")
            if props.expand_rig:
                rcols = get_bone_collections(rig_obj.data)

                arm_L = [c for c in rcols if "Arm.L" in c.name]
                arm_R = [c for c in rcols if "Arm.R" in c.name]
                leg_L = [c for c in rcols if "Leg.L" in c.name]
                leg_R = [c for c in rcols if "Leg.R" in c.name]

                fingers = next((c for c in rcols if c.name == "Fingers"), None)
                fingers_detail = next((c for c in rcols if c.name == "Fingers Detail"), None)
                torso = next((c for c in rcols if c.name == "Torso"), None)
                torso_tweak = next((c for c in rcols if c.name == "Torso Tweak"), None)
                gaze = next((c for c in rcols if c.name == "Gaze"), None)
                tongue = next((c for c in rcols if c.name == "Tongue"), None)
                root = next((c for c in rcols if c.name == "Root"), None)

                def draw_pair(col_box, left, right, title, icon="GROUP_BONE"):
                    col_box.label(text=title, icon=icon)
                    m = max(len(left), len(right))
                    for i in range(m):
                        row = col_box.row(align=True)
                        L = left[i] if i < len(left) else None
                        R = right[i] if i < len(right) else None
                        row.prop(L, "is_visible", text=L.name, toggle=True) if L else row.label(text="")
                        row.separator(factor=1.2)
                        row.prop(R, "is_visible", text=R.name, toggle=True) if R else row.label(text="")

                col_box = box.box()

                head_L = [c for c in rcols if c.name == "Basic Face"]
                head_R = [c for c in rcols if c.name == "Face Deform"]
                if head_L or head_R or gaze or tongue:
                    draw_pair(col_box, head_L, head_R, "Head", icon="ARMATURE_DATA")

                    if gaze or tongue:
                        row = col_box.row(align=True)
                        row.prop(gaze, "is_visible", text="Gaze", toggle=True) if gaze else row.label(text="")
                        row.separator(factor=1.2)
                        row.prop(tongue, "is_visible", text="Tongue", toggle=True) if tongue else row.label(text="")

                    if "gazeFollowHead" in rig_obj.data.keys():
                        gbox = col_box.box()
                        gbox.label(text="Gaze Options", icon="HIDE_OFF")
                        gbox.prop(rig_obj.data, '["gazeFollowHead"]', text="Follow Head", slider=True)

                draw_pair(col_box, arm_L, arm_R, "Arms", icon="ARMATURE_DATA")

                row = col_box.row(align=True)
                row.prop(fingers, "is_visible", text="Fingers", toggle=True) if fingers else row.label(text="")
                row.separator(factor=1.2)
                row.prop(fingers_detail, "is_visible", text="Fingers Detail", toggle=True) if fingers_detail else row.label(text="")

                if leg_L or leg_R:
                    draw_pair(col_box, leg_L, leg_R, "Legs", icon="BONE_DATA")

                has_torso = bool(torso)
                has_tweak = bool(torso_tweak)
                if has_torso or has_tweak:
                    col_box.label(text="Torso", icon="MOD_ARMATURE")
                    if has_torso and not has_tweak:
                        row = col_box.row(align=True)
                        row.prop(torso, "is_visible", text="Torso", toggle=True)
                    elif has_torso and has_tweak:
                        row = col_box.row(align=True)
                        row.prop(torso, "is_visible", text="Torso", toggle=True)
                        row.separator(factor=1.2)
                        row.prop(torso_tweak, "is_visible", text="Torso Tweak", toggle=True)
                    elif has_tweak and not has_torso:
                        row = col_box.row(align=True)
                        row.prop(torso_tweak, "is_visible", text="Torso Tweak", toggle=True)

                if root:
                    col_box.label(text="Root", icon="OBJECT_ORIGIN")
                    col_box.prop(root, "is_visible", text="Root", toggle=True)
        
        _panel_draw_pose_tools_block(layout, context)
        _panel_draw_ikfk_block(layout, context)
        _panel_draw_info_block(layout, context)
       
       
# ------------------------------------------------------------
# Pose Tools block
# ------------------------------------------------------------
def _panel_draw_pose_tools_block(layout, context):
    sc    = context.scene
    props = sc.axis_panel_props

    box = layout.box()
    hdr = box.row()
    hdr.prop(props, "expand_pose_tools", text="",
             icon="TRIA_DOWN" if props.expand_pose_tools else "TRIA_RIGHT", emboss=False)
    hdr.label(text="Pose Tools", icon="POSE_HLT")

    if not props.expand_pose_tools:
        return

    col = box.column(align=True)

    r = col.row(align=True); r.scale_y = 1.2
    r.operator("axis_panel.reset_pose", icon="RECOVER_LAST", text="Reset Pose")

    col.separator()

    in_pose = context.mode == 'POSE'
    r = col.row(align=True); r.scale_y = 1.2
    r.operator(
        "axis_panel.toggle_mode",
        icon="OBJECT_DATAMODE" if in_pose else "POSE_HLT",
        text="Switch to Object" if in_pose else "Switch to Pose",
    )

    col.separator()

    limits_box = box.box()
    limits_on = _panel_limits_active(_panel_get_main_rig(context))
    r = limits_box.row(align=True); r.scale_y = 1.2
    r.operator(
        "axis_panel.toggle_limits",
        icon="LOCKED" if limits_on else "UNLOCKED",
        text="Disable Limits" if limits_on else "Enable Limits",
        depress=not limits_on,
    )

    col.separator()

    inner = box.box()
    inner.label(text="Pose Clipboard", icon="COPYDOWN")
    row = inner.row(align=True)
    row.operator("axis_panel.copy_pose",  icon="COPYDOWN",  text="Copy Pose")
    op = row.operator("axis_panel.paste_pose", icon="PASTEDOWN", text="Paste Pose")
    op.flipped = False

    row2 = inner.row(align=True)
    op = row2.operator("axis_panel.paste_pose", icon="MOD_MIRROR", text="Paste Flipped Pose")
    op.flipped = True

    inner.separator(factor=0.5)

    flip_box = inner.box()
    flip_box.row().label(text="Flip Pose", icon="ARROW_LEFTRIGHT")
    row = flip_box.row(align=True)
    op = row.operator("axis_panel.side_mirror", text="Flip Left \u2192 Right")
    op.src = 'L'; op.mode = 'FLIP'
    op = row.operator("axis_panel.side_mirror", text="Flip Right \u2192 Left")
    op.src = 'R'; op.mode = 'FLIP'

    mir_box = inner.box()
    mir_box.row().label(text="Mirror Pose", icon="MOD_MIRROR")
    row = mir_box.row(align=True)
    op = row.operator("axis_panel.side_mirror", text="Copy Left \u2192 Right")
    op.src = 'L'; op.mode = 'MIRROR'
    op = row.operator("axis_panel.side_mirror", text="Copy Right \u2192 Left")
    op.src = 'R'; op.mode = 'MIRROR'


# ------------------------------------------------------------
# Advanced Pose Tools block
# ------------------------------------------------------------
def _panel_draw_ikfk_block(layout, context):
    sc    = context.scene
    props = sc.axis_panel_props
    rig   = _panel_get_main_rig(context)

    has_legs    = _panel_has_legs(rig)
    has_fingers = bool(rig and rig.pose and rig.pose.bones.get("thumb.01_ik.L"))
    pbones      = rig.pose.bones if (rig and rig.pose) else {}
    all_ik      = _panel_all_limbs_ik(rig, include_legs=has_legs) if rig else False

    def _fkik_val(bn, key):
        pb = pbones.get(bn)
        if pb and key in pb.keys():
            try: return float(pb[key])
            except Exception: pass
        return 0.0

    box = layout.box()
    hdr = box.row()
    hdr.prop(props, "expand_adv_pose_tools", text="",
             icon="TRIA_DOWN" if props.expand_adv_pose_tools else "TRIA_RIGHT", emboss=False)
    hdr.label(text="Advanced Pose Tools", icon="ARMATURE_DATA")

    if not props.expand_adv_pose_tools:
        return

    # ── IK/FK Sliders ─────────────────────────────────────
    inner = box.box()
    inner.label(text="IK/FK Switch", icon='CONSTRAINT_BONE')
    row = inner.row(align=True)
    colL = row.column(align=True)
    colR = row.column(align=True)

    colL.label(text="Left")
    if hasattr(sc, "axis_panel_arm_ikfk_L"):
        colL.prop(sc, "axis_panel_arm_ikfk_L", text="Arm IK↔FK")
    if has_legs and hasattr(sc, "axis_panel_leg_ikfk_L"):
        colL.prop(sc, "axis_panel_leg_ikfk_L", text="Leg IK↔FK")

    colR.label(text="Right")
    if hasattr(sc, "axis_panel_arm_ikfk_R"):
        colR.prop(sc, "axis_panel_arm_ikfk_R", text="Arm IK↔FK")
    if has_legs and hasattr(sc, "axis_panel_leg_ikfk_R"):
        colR.prop(sc, "axis_panel_leg_ikfk_R", text="Leg IK↔FK")

    inner.separator()
    inner.label(text="Fingers FK/IK", icon='HAND')
    fr = inner.row(align=True)
    if hasattr(sc, "axis_panel_fingers_fkik_L"):
        fr.prop(sc, "axis_panel_fingers_fkik_L", text="Left Hand")
    if hasattr(sc, "axis_panel_fingers_fkik_R"):
        fr.prop(sc, "axis_panel_fingers_fkik_R", text="Right Hand")

    # ── Global toggles ─────────────────────────────────────
    inner.separator()
    inner.label(text="Global Controls", icon='OUTLINER_OB_ARMATURE')
    col = inner.column(align=True)
    row = col.row(align=True); row.scale_y = 1.2
    txt = "Global FK (Arms & Legs)" if has_legs else "Global FK (Arms)"
    row.operator("axis_panel.toggle_ikfk_limbs_global", text=txt,
                 icon='OUTLINER_OB_ARMATURE', depress=all_ik)
    row = col.row(align=True); row.scale_y = 1.2
    both_fk_ik = (_fkik_val("thumb.01_ik.L", "FK_IK") >= 0.5 and
                  _fkik_val("thumb.01_ik.R", "FK_IK") >= 0.5)
    row.operator("axis_panel.toggle_fkik_fingers_global", text="Global Fingers IK",
                 icon='HAND', depress=both_fk_ik)

    # ── Snap FK/IK ─────────────────────────────────────────
    snap_box = box.box()
    snap_box.label(text="Snap FK/IK", icon='SNAP_ON')

    row = snap_box.row()
    cL = row.column(align=True)
    cR = row.column(align=True)

    cL.label(text="Left Arm")
    op = cL.operator("axis_panel.snap", text="FK → IK")
    op.side = 'L'; op.limb = 'arm'; op.direction = 'FK2IK'
    op = cL.operator("axis_panel.snap", text="IK → FK")
    op.side = 'L'; op.limb = 'arm'; op.direction = 'IK2FK'

    cR.label(text="Right Arm")
    op = cR.operator("axis_panel.snap", text="FK → IK")
    op.side = 'R'; op.limb = 'arm'; op.direction = 'FK2IK'
    op = cR.operator("axis_panel.snap", text="IK → FK")
    op.side = 'R'; op.limb = 'arm'; op.direction = 'IK2FK'

    if has_legs:
        cL.separator()
        cL.label(text="Left Leg")
        op = cL.operator("axis_panel.snap", text="FK → IK")
        op.side = 'L'; op.limb = 'leg'; op.direction = 'FK2IK'
        op = cL.operator("axis_panel.snap", text="IK → FK")
        op.side = 'L'; op.limb = 'leg'; op.direction = 'IK2FK'

        cR.separator()
        cR.label(text="Right Leg")
        op = cR.operator("axis_panel.snap", text="FK → IK")
        op.side = 'R'; op.limb = 'leg'; op.direction = 'FK2IK'
        op = cR.operator("axis_panel.snap", text="IK → FK")
        op.side = 'R'; op.limb = 'leg'; op.direction = 'IK2FK'

    if has_fingers:
        cL.separator()
        cL.label(text="Left Fingers")
        op = cL.operator("axis_panel.snap_fingers", text="FK → IK")
        op.side = 'L'; op.direction = 'FK2IK'
        op = cL.operator("axis_panel.snap_fingers", text="IK → FK")
        op.side = 'L'; op.direction = 'IK2FK'

        cR.separator()
        cR.label(text="Right Fingers")
        op = cR.operator("axis_panel.snap_fingers", text="FK → IK")
        op.side = 'R'; op.direction = 'FK2IK'
        op = cR.operator("axis_panel.snap_fingers", text="IK → FK")
        op.side = 'R'; op.direction = 'IK2FK'

    snap_box.separator()
    row = snap_box.row(align=True); row.scale_y = 1.2
    row.operator("axis_panel.snap_global_fk2ik", icon='SNAP_ON', text="Global FK → IK")
    row.separator()
    row.operator("axis_panel.snap_global_ik2fk", icon='SNAP_ON', text="Global IK → FK")

    # ── Stretch controls ───────────────────────────────────
    stretch_box = box.box()
    stretch_box.label(text="Stretch Controls", icon='FULLSCREEN_EXIT')
    row = stretch_box.row(align=True)
    cL = row.column(align=True)
    cR = row.column(align=True)

    cL.label(text="Left", icon='TRIA_LEFT')
    pb_uaL = pbones.get("upper_arm_parent.L")
    if pb_uaL and "IK_Stretch" in pb_uaL.keys():
        cL.prop(pb_uaL, '["IK_Stretch"]', text="Arm Stretch")
    if has_legs:
        pb_thL = pbones.get("thigh_parent.L")
        if pb_thL and "IK_Stretch" in pb_thL.keys():
            cL.prop(pb_thL, '["IK_Stretch"]', text="Leg Stretch")

    cR.label(text="Right", icon='TRIA_RIGHT')
    pb_uaR = pbones.get("upper_arm_parent.R")
    if pb_uaR and "IK_Stretch" in pb_uaR.keys():
        cR.prop(pb_uaR, '["IK_Stretch"]', text="Arm Stretch")
    if has_legs:
        pb_thR = pbones.get("thigh_parent.R")
        if pb_thR and "IK_Stretch" in pb_thR.keys():
            cR.prop(pb_thR, '["IK_Stretch"]', text="Leg Stretch")


# ------------------------------------------------------------
# Info
# ------------------------------------------------------------
def _panel_draw_info_block(layout, context):
    props = context.scene.axis_panel_props
    box = layout.box()
    hdr = box.row()
    hdr.prop(props, "expand_info", text="", icon="TRIA_DOWN" if props.expand_info else "TRIA_RIGHT", emboss=False)
    hdr.label(text="Info", icon="INFO")
    if props.expand_info:
        inner = box.box()
        col = inner.column(align=True)
        col.label(text=f"AXIS Panel — Version {PANEL_VERSION_STR}", icon="FILE_BLEND")
        col.separator(factor=0.6)

        # ── Update check ──
        st = _update_state
        if st["status"] == "idle":
            col.operator("axis_panel.check_update", text="Check for Updates", icon="URL")
        elif st["status"] == "checking":
            col.label(text="Checking...", icon="TIME")
        elif st["status"] == "up_to_date":
            v = ".".join(map(str, st["remote_version"]))
            col.label(text=f"Up to date  ({v})", icon="CHECKMARK")
            col.operator("axis_panel.check_update", text="Check Again", icon="FILE_REFRESH")
        elif st["status"] == "available":
            v = ".".join(map(str, st["remote_version"]))
            col.label(text=f"Update available: {v}", icon="ERROR")
            col.operator("axis_panel.download_update", text="Update Panel", icon="IMPORT")
        elif st["status"] == "error":
            col.label(text="Could not check for updates.", icon="ERROR")
            col.operator("axis_panel.check_update", text="Retry", icon="FILE_REFRESH")

        col.separator(factor=1.2)
        
        note_box = inner.box()
        note_box.label(text="Note", icon="INFO")
        note_col = note_box.column(align=True)
        note_col.label(text="For advanced features, install the AXIS Core Add-on.")
        note_col.label(text="Includes auto-retargeting (Mixamo, DAZ, Unreal...),")
        note_col.label(text="Face Mocap via Live Link (ARKit), and more.")
        note_col.separator(factor=0.8)
        note_col.operator("wm.url_open", text="AXIS Core Add-on", icon="PLUGIN").url = "https://superhivemarket.com/products/axis-core-addon-for-blender"
        col.separator(factor=1.4)

        r = col.row(align=True)
        r.operator("wm.url_open", text="Documentation", icon="HELP").url = "https://axisproject.co/documentation"
        col.separator(factor=0.6)
        r = col.row(align=True)
        r.operator("wm.url_open", text="Tutorials", icon="PLAY").url = "https://www.youtube.com/playlist?list=PLULNUwDQZpCZnWmO3qFrcNB0OkMJqjd4Y"
        col.separator(factor=2.0)

        r = col.row(align=True)
        r.operator("wm.url_open", text="Need more characters?", icon="ARMATURE_DATA").url = "https://superhivemarket.com/creators/thecatempire"
        col.separator(factor=0.6)
        r = col.row(align=True)
        r.operator("wm.url_open", text="Support", icon="FUND").url = "mailto:thecatempirestudio@gmail.com"


# -----------------------------
# Update operators
# -----------------------------

class AXISPANEL_OT_CheckUpdate(bpy.types.Operator):
    bl_idname    = "axis_panel.check_update"
    bl_label     = "Check for Updates"
    bl_description = "Check for a newer version of the AXIS Panel."
    bl_options   = {'INTERNAL'}

    def execute(self, context):
        _update_state["status"] = "checking"
        _update_state["remote_version"] = None

        def _check():
            try:
                with _urllib_request.urlopen(_VERSION_URL, timeout=8, context=_ssl_ctx) as resp:
                    data = json.loads(resp.read().decode())
                remote = tuple(data["version"])
                _update_state["remote_version"] = remote
                _update_state["status"] = "available" if remote > PANEL_VERSION else "up_to_date"
            except Exception:
                _update_state["status"] = "error"
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    area.tag_redraw()

        threading.Thread(target=_check, daemon=True).start()
        return {'FINISHED'}


class AXISPANEL_OT_DownloadUpdate(bpy.types.Operator):
    bl_idname    = "axis_panel.download_update"
    bl_label     = "Update Panel"
    bl_description = "Download and install the latest AXIS Panel from GitHub."
    bl_options   = {'INTERNAL'}

    def execute(self, context):
        try:
            with _urllib_request.urlopen(_PANEL_RAW_URL, timeout=15, context=_ssl_ctx) as resp:
                src = resp.read().decode("utf-8")
        except Exception as e:
            self.report({'ERROR'}, f"Download failed: {e}")
            return {'CANCELLED'}

        txt = bpy.data.texts.get("AXIS_Panel.py")
        if not txt:
            self.report({'ERROR'}, "AXIS_Panel.py text block not found.")
            return {'CANCELLED'}

        txt.clear()
        txt.write(src)

        try:
            exec(compile(src, "AXIS_Panel.py", "exec"), {"__name__": "__main__"})
        except Exception as e:
            self.report({'ERROR'}, f"Execution error: {e}")
            return {'CANCELLED'}

        _update_state["status"] = "idle"
        _update_state["remote_version"] = None
        self.report({'INFO'}, "AXIS Panel updated. Restart recommended to fully apply changes.")
        return {'FINISHED'}


# -----------------------------
# Registration
# -----------------------------

classes = [
    AXIS_PanelProps,
    AXIS_PT_MainPanel,
    AXIS_OT_SetLegend,
    AXIS_OT_ToggleSimplify,
    AXIS_OT_panel_toggle_ikfk_limbs_global,
    AXIS_OT_panel_toggle_fkik_fingers_global,
    AXIS_OT_panel_snap_fingers,
    AXIS_OT_panel_snap,
    AXIS_OT_panel_snap_global_fk2ik,
    AXIS_OT_panel_snap_global_ik2fk,
    AXIS_OT_panel_reset_pose,
    AXIS_OT_panel_toggle_mode,
    AXIS_OT_panel_toggle_limits,
    AXIS_OT_panel_copy_pose,
    AXIS_OT_panel_paste_pose,
    AXIS_OT_panel_side_mirror,
    AXISPANEL_OT_CheckUpdate,
    AXISPANEL_OT_DownloadUpdate,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.axis_panel_props = bpy.props.PointerProperty(type=AXIS_PanelProps)

    Scene = bpy.types.Scene
    Scene.axis_panel_rig = bpy.props.PointerProperty(
        name="AXIS Rig",
        description="Active AXIS rig controlled by this panel",
        type=bpy.types.Object,
        poll=lambda self, obj: _panel_is_axis_rig(obj),
    )
    Scene.axis_panel_arm_ikfk_L = bpy.props.FloatProperty(
        name="Arm IK/FK L", min=0.0, max=1.0, default=1.0,
        update=_panel_make_arm_update('L'))
    Scene.axis_panel_arm_ikfk_R = bpy.props.FloatProperty(
        name="Arm IK/FK R", min=0.0, max=1.0, default=1.0,
        update=_panel_make_arm_update('R'))
    Scene.axis_panel_leg_ikfk_L = bpy.props.FloatProperty(
        name="Leg IK/FK L", min=0.0, max=1.0, default=1.0,
        update=_panel_make_leg_update('L'))
    Scene.axis_panel_leg_ikfk_R = bpy.props.FloatProperty(
        name="Leg IK/FK R", min=0.0, max=1.0, default=1.0,
        update=_panel_make_leg_update('R'))
    Scene.axis_panel_fingers_fkik_L = bpy.props.FloatProperty(
        name="Fingers FK/IK L", min=0.0, max=1.0, default=0.0,
        update=_panel_make_fingers_update('L'))
    Scene.axis_panel_fingers_fkik_R = bpy.props.FloatProperty(
        name="Fingers FK/IK R", min=0.0, max=1.0, default=0.0,
        update=_panel_make_fingers_update('R'))

    widget_obj = next(
        (obj for obj in bpy.data.objects if obj.type == "ARMATURE" and obj.data.get("widget_id") and "widget" in obj.name.lower()),
        None,
    )
    if widget_obj:
        for coll in get_bone_collections(widget_obj.data):
            if coll.name == LEGEND_MAIN:
                coll.is_visible = False
    
    if not hasattr(bpy.types.WindowManager, "axis_panel_ikfk_expanded"):
        bpy.types.WindowManager.axis_panel_ikfk_expanded = bpy.props.BoolProperty(
            name="IK/FK Quick Switch",
            description="Expand or collapse the IK/FK quick switch block",
            default=True
        )

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    Scene = bpy.types.Scene
    for attr in (
        "axis_panel_rig",
        "axis_panel_props",
        "axis_panel_arm_ikfk_L", "axis_panel_arm_ikfk_R",
        "axis_panel_leg_ikfk_L", "axis_panel_leg_ikfk_R",
        "axis_panel_fingers_fkik_L", "axis_panel_fingers_fkik_R",
    ):
        if hasattr(Scene, attr):
            try:
                delattr(Scene, attr)
            except Exception:
                pass

    if hasattr(bpy.types.WindowManager, "axis_panel_ikfk_expanded"):
        del bpy.types.WindowManager.axis_panel_ikfk_expanded

if __name__ == "__main__":
    register()
