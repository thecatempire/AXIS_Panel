# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Antonio Solano (AXIS Project)
# Project: AXIS Rig Panel
# Module: AXIS_Rig_Panel.py
# Documentation: https://www.axisproject.co/documentation
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later version.
# It is distributed WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public
# License for more details: <https://www.gnu.org/licenses/>.

__author__ = "Antonio Solano"
__license__ = "GPL-3.0-or-later"
PANEL_VERSION = (2, 0, 0)
PANEL_VERSION_STR = ".".join(map(str, PANEL_VERSION))

import json
import re
import ssl
import threading
from urllib import request as _urllib_request

import bpy
import mathutils


def _make_ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_ssl_ctx = _make_ssl_context()
_VERSION_URL = "https://raw.githubusercontent.com/thecatempire/AXIS_Panel/main/version_rig_panel.json"
_PANEL_RAW_URL = "https://raw.githubusercontent.com/thecatempire/AXIS_Panel/main/AXIS_Rig_Panel.py"
TEXT_NAME = "AXIS_Rig_Panel.py"
_update_state = {"status": "idle", "remote_version": None}

CATEGORY = "AXIS Rig"
TECHNICAL = {"Dev", "MCH", "DEF", "ORG"}
FACE_WIDGET = "Face Widget"
ARM_PARENTS = ("upper_arm_parent.L", "upper_arm_parent.R")
LEG_PARENTS = ("thigh_parent.L", "thigh_parent.R")
FINGERS = ("thumb", "f_index", "f_middle", "f_ring", "f_pinky")


def rig_version(obj):
    if not (obj and getattr(obj, "type", "") == 'ARMATURE'):
        return None
    version = obj.data.get("axis_rig_version")
    return int(version) if version is not None else None


def is_axis_rig(obj):
    return rig_version(obj) is not None


def main_rig(context):
    rig = getattr(context.scene, "axis_rig_panel_rig", None)
    return rig if is_axis_rig(rig) else None


def rig_id(rig):
    value = rig.data.get("rig_id") if rig else None
    return str(value) if value else None


def rigify_operator(rig, name):
    rid = rig_id(rig)
    if not rid:
        return None
    op = getattr(bpy.ops.pose, f"{name}_{rid}", None)
    try:
        op.get_rna_type()
    except (AttributeError, KeyError):
        return None
    return op


_spec_cache = {}


def control_spec(rig):
    source = rig.data.get("axis_ui") if rig else None
    if not source:
        return None
    key = rig.data.as_pointer()
    cached = _spec_cache.get(key)
    if cached is None or cached[0] != source:
        cached = (source, json.loads(source))
        _spec_cache[key] = cached
    return cached[1]


def rigify_button(rig, op, text):
    spec = control_spec(rig)
    if spec is None:
        return None
    stack = [item for group in spec["groups"] for item in group["items"]]
    while stack:
        item = stack.pop()
        if item["kind"] == "operator" and item["op"] == op and item.get("text") == text:
            return {key: tuple(value) if isinstance(value, list) else value for key, value in item["params"].items()}
        stack.extend(item.get("items", []))
    return None


def bone_prop(rig, bone, prop, default=0.0):
    pose_bone = rig.pose.bones.get(bone) if (rig and rig.pose) else None
    if pose_bone is not None and prop in pose_bone.keys():
        try:
            return float(pose_bone[prop])
        except (TypeError, ValueError):
            pass
    return float(default)


def set_bone_prop(rig, bone, prop, value):
    pose_bone = rig.pose.bones.get(bone) if (rig and rig.pose) else None
    if pose_bone is not None and prop in pose_bone.keys():
        pose_bone[prop] = float(value)


def has_bone(rig, name):
    return bool(rig and rig.pose and rig.pose.bones.get(name))


def is_selected(pose_bone):
    selected = getattr(pose_bone, "select", None)
    return pose_bone.bone.select if selected is None else selected


_POSE_HIDE = re.compile(r'^pose\.bones\["(.+)"\]\.hide$')
_BONE_HIDE = re.compile(r'^bones\["(.+)"\]\.hide$')


def _copy_driver(source, holder, path):
    target = holder.driver_add(path)
    driver, original = target.driver, source.driver
    driver.type = original.type
    driver.expression = original.expression
    driver.use_self = original.use_self
    for variable in original.variables:
        copy = driver.variables.new()
        copy.name, copy.type = variable.name, variable.type
        for index, item in enumerate(variable.targets):
            other = copy.targets[index]
            if variable.type == 'SINGLE_PROP':
                other.id_type = item.id_type
            other.id = item.id
            for key in ("data_path", "bone_target", "transform_type", "transform_space", "rotation_mode"):
                setattr(other, key, getattr(item, key))
    while len(target.modifiers) > len(source.modifiers):
        target.modifiers.remove(target.modifiers[-1])
    return target


def adapt_visibility_drivers():
    pose_hide = bpy.types.PoseBone.bl_rna.properties.get("hide") is not None
    moved = 0
    for rig in [obj for obj in bpy.data.objects if is_axis_rig(obj)]:
        source, target = (rig.data, rig) if pose_hide else (rig, rig.data)
        pattern = _BONE_HIDE if pose_hide else _POSE_HIDE
        prefix = 'pose.bones["{}"].hide' if pose_hide else 'bones["{}"].hide'
        if source.animation_data is None:
            continue
        for fcurve in list(source.animation_data.drivers):
            match = pattern.match(fcurve.data_path)
            if match is None or match.group(1) not in rig.data.bones:
                continue
            _copy_driver(fcurve, target, prefix.format(match.group(1)))
            source.animation_data.drivers.remove(fcurve)
            moved += 1
    return moved


@bpy.app.handlers.persistent
def _adapt_on_load(*_args):
    adapt_visibility_drivers()


def has_legs(rig):
    return all(has_bone(rig, name) for name in LEG_PARENTS)


def has_arms(rig):
    return all(has_bone(rig, name) for name in ARM_PARENTS)


def refresh(context, rig=None):
    if rig is not None:
        rig.update_tag()
        rig.data.update_tag()
    context.view_layer.update()
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'DOPESHEET_EDITOR', 'GRAPH_EDITOR'}:
                area.tag_redraw()


class pose_mode_on:
    def __init__(self, context, rig):
        self.context, self.rig = context, rig

    def _mode_set(self, obj, mode):
        with self.context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
            bpy.ops.object.mode_set(mode=mode)

    def __enter__(self):
        view_layer = self.context.view_layer
        self.rig_mode = self.rig.mode
        self.previous = view_layer.objects.active
        self.previous_mode = self.previous.mode if self.previous else 'OBJECT'
        if self.previous is not None and self.previous != self.rig and self.previous.mode != 'OBJECT':
            self._mode_set(self.previous, 'OBJECT')
        view_layer.objects.active = self.rig
        self.rig.select_set(True)
        if self.rig.mode != 'POSE':
            self._mode_set(self.rig, 'POSE')
        return self.rig

    def __exit__(self, *exc):
        if self.previous is not None and self.previous != self.rig and self.previous.name in self.context.view_layer.objects:
            self._mode_set(self.rig, 'OBJECT')
            self.context.view_layer.objects.active = self.previous
            if self.previous_mode != 'OBJECT':
                self._mode_set(self.previous, self.previous_mode)
        elif self.rig.mode != self.rig_mode:
            self._mode_set(self.rig, self.rig_mode)


def all_collections(armature):
    found = getattr(armature, "collections_all", None)
    return found if found is not None else armature.collections


def children_of(collection, armature):
    children = getattr(collection, "children", None)
    if children is not None:
        return list(children)
    if collection.name != FACE_WIDGET:
        return []
    return [c for c in all_collections(armature) if c != collection and len(c.bones)
            and all(bone.name.startswith("wg_") for bone in c.bones)]


def widget_collections(rig):
    parent = all_collections(rig.data).get(FACE_WIDGET)
    return parent, (children_of(parent, rig.data) if parent else []), "faceWidgetFollowHead" in rig.data.keys()


_DOTTED = re.compile(r"^(.*)\.([LR])((?:\.\d+)?)$")
_UNDERSCORE = re.compile(r"^(.*)_([LR])((?:\.\d+)?)$")
_CAMEL = re.compile(r"^(.*[a-z0-9\-])([LR])((?:Ctrl\d*|Aim|Ctrl\.\d+)?)$")
_WORD = re.compile(r"^(.*)(Left|Right)(.*)$")


def mirror_name(name):
    for pattern in (_DOTTED, _UNDERSCORE, _CAMEL):
        match = pattern.match(name)
        if match:
            head, side, tail = match.groups()
            other = "R" if side == "L" else "L"
            separator = name[len(head):len(name) - len(tail) - 1]
            return f"{head}{separator}{other}{tail}"
    match = _WORD.match(name)
    if match:
        head, side, tail = match.groups()
        return f"{head}{'Right' if side == 'Left' else 'Left'}{tail}"
    return None


def side_of(name):
    mirrored = mirror_name(name)
    if mirrored is None:
        return None
    for pattern in (_DOTTED, _UNDERSCORE, _CAMEL):
        match = pattern.match(name)
        if match:
            return match.group(2)
    return "L" if "Left" in name else "R"


_MIRROR_X = mathutils.Matrix.Diagonal((-1.0, 1.0, 1.0))


def mirror_basis(rig, name, other):
    source = rig.data.bones[name].matrix_local.to_3x3()
    target = rig.data.bones[other].matrix_local.to_3x3()
    return target.inverted() @ _MIRROR_X @ source


def _mirrored_transform(basis, location, mode, quaternion, euler, axis_angle, scale):
    location = basis @ location
    if mode == 'QUATERNION':
        matrix = quaternion.to_matrix()
    elif mode == 'AXIS_ANGLE':
        matrix = mathutils.Quaternion(axis_angle[1:], axis_angle[0]).to_matrix()
    else:
        matrix = euler.to_matrix()
    matrix = basis @ matrix @ basis.inverted()
    if mode == 'QUATERNION':
        rotation = matrix.to_quaternion()
    elif mode == 'AXIS_ANGLE':
        axis, angle = matrix.to_quaternion().to_axis_angle()
        rotation = (angle, axis.x, axis.y, axis.z)
    else:
        rotation = matrix.to_euler(mode, euler)
    return location, mode, rotation, scale.copy()


def _apply_transform(pose_bone, transform):
    location, mode, rotation, scale = transform
    pose_bone.location = location
    pose_bone.rotation_mode = mode
    if mode == 'QUATERNION':
        pose_bone.rotation_quaternion = rotation
    elif mode == 'AXIS_ANGLE':
        pose_bone.rotation_axis_angle = rotation
    else:
        pose_bone.rotation_euler = rotation
    pose_bone.scale = scale


def _snapshot(pose_bone):
    return (pose_bone.location.copy(), pose_bone.rotation_mode, pose_bone.rotation_quaternion.copy(),
            pose_bone.rotation_euler.copy(), tuple(pose_bone.rotation_axis_angle), pose_bone.scale.copy())


class AXISRIGPANEL_Props(bpy.types.PropertyGroup):
    expand_widget: bpy.props.BoolProperty(name="Face Widget", default=True)
    expand_rig: bpy.props.BoolProperty(name="Rig Layers", default=False)
    expand_selected: bpy.props.BoolProperty(name="Selected Controls", default=True)
    expand_ikfk: bpy.props.BoolProperty(name="IK / FK", default=False)
    expand_pose_tools: bpy.props.BoolProperty(name="Pose Tools", default=False)
    expand_performance: bpy.props.BoolProperty(name="Performance", default=False)
    expand_info: bpy.props.BoolProperty(name="Info", default=False)


class AXISRIGPANEL_OT_ToggleSimplify(bpy.types.Operator):
    bl_idname = "axis_rig_panel.toggle_simplify"
    bl_label = "Toggle Simplify"
    bl_description = "Enable or disable Simplify for the viewport"

    def execute(self, context):
        render = context.scene.render
        render.use_simplify = not render.use_simplify
        return {'FINISHED'}


class AXISRIGPANEL_OT_limbs_ikfk(bpy.types.Operator):
    bl_idname = "axis_rig_panel.toggle_ikfk_limbs_global"
    bl_label = "All Limbs IK / FK"
    bl_description = "Switch every arm and leg to FK, or back to IK when they all are"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = main_rig(context)
        if rig is None:
            return {'CANCELLED'}
        parents = [n for n in ARM_PARENTS + LEG_PARENTS if has_bone(rig, n)]
        all_fk = all(bone_prop(rig, n, "IK_FK") >= 0.5 for n in parents)
        for name in parents:
            set_bone_prop(rig, name, "IK_FK", 0.0 if all_fk else 1.0)
        refresh(context, rig)
        return {'FINISHED'}


class AXISRIGPANEL_OT_fingers(bpy.types.Operator):
    bl_idname = "axis_rig_panel.set_fingers"
    bl_label = "Fingers IK / FK"
    bl_description = "Set every finger of the hand to IK or FK"
    bl_options = {'REGISTER', 'UNDO'}

    side: bpy.props.StringProperty(default="L", options={'HIDDEN'})
    value: bpy.props.FloatProperty(default=1.0, options={'HIDDEN'})

    def execute(self, context):
        rig = main_rig(context)
        if rig is None:
            return {'CANCELLED'}
        for side in ("L", "R") if self.side == "BOTH" else (self.side,):
            for finger in FINGERS:
                set_bone_prop(rig, f"{finger}.01_ik.{side}", "FK_IK", self.value)
        refresh(context, rig)
        return {'FINISHED'}


def _limb_bones(limb, side):
    if limb == "arm":
        return ([f"upper_arm_fk.{side}", f"forearm_fk.{side}", f"hand_fk.{side}"],
                [f"upper_arm_ik.{side}", f"MCH-forearm_ik.{side}", f"MCH-upper_arm_ik_target.{side}"],
                [f"upper_arm_ik.{side}", f"upper_arm_ik_target.{side}", f"hand_ik.{side}"],
                f"upper_arm_parent.{side}")
    return ([f"thigh_fk.{side}", f"shin_fk.{side}", f"foot_fk.{side}"],
            [f"thigh_ik.{side}", f"MCH-shin_ik.{side}", f"MCH-thigh_ik_target.{side}"],
            [f"thigh_ik.{side}", f"thigh_ik_target.{side}", f"foot_ik.{side}"],
            f"thigh_parent.{side}")


def snap_limb(rig, limb, side, direction):
    fk, ik, ctrl, prop_bone = _limb_bones(limb, side)
    if not has_bone(rig, prop_bone):
        return False
    end = "hand" if limb == "arm" else "foot"
    op = "rigify_generic_snap" if direction == "FK2IK" else "rigify_limb_ik2fk"
    label = "FK->IK" if direction == "FK2IK" else "IK->FK"
    params = rigify_button(rig, f"pose.{op}", f"{label} ({end}.{side})")
    if params is not None:
        rigify_operator(rig, op)(**params)
        return True
    if direction == "FK2IK":
        rigify_operator(rig, "rigify_generic_snap")(
            output_bones=json.dumps(fk), input_bones=json.dumps(ik), ctrl_bones=json.dumps(ctrl))
    else:
        rigify_operator(rig, "rigify_limb_ik2fk")(
            prop_bone=prop_bone, fk_bones=json.dumps(fk), ik_bones=json.dumps(ik), ctrl_bones=json.dumps(ctrl),
            tail_bones=json.dumps([]), extra_ctrls=json.dumps([]))
    return True


def snap_fingers(rig, side, direction):
    for finger in FINGERS:
        ik_control = f"{finger}.01_ik.{side}"
        if not has_bone(rig, ik_control):
            continue
        fk_master = f"{finger}.01_master.{side}"
        fk_chain = [f"{finger}.01.{side}", f"{finger}.02.{side}", f"{finger}.03.{side}", f"{finger}.01.{side}.001"]
        op = "rigify_finger_fk2ik" if direction == "FK2IK" else "rigify_generic_snap"
        label = "FK->IK" if direction == "FK2IK" else "IK->FK"
        params = rigify_button(rig, f"pose.{op}", f"{label} ({finger}.01.{side})")
        if params is not None:
            rigify_operator(rig, op)(**params)
            continue
        if direction == "FK2IK":
            rigify_operator(rig, "rigify_finger_fk2ik")(
                fk_master=fk_master, fk_chain=json.dumps(fk_chain),
                ik_chain=json.dumps([f"ORG-{finger}.01.{side}", f"ORG-{finger}.02.{side}", f"ORG-{finger}.03.{side}"]),
                ik_control=ik_control, constraint_bone=f"ORG-{finger}.03.{side}", axis='+X')
        else:
            rigify_operator(rig, "rigify_generic_snap")(
                output_bones=json.dumps([ik_control]), input_bones=json.dumps([fk_chain[3]]),
                ctrl_bones=json.dumps([fk_master] + fk_chain), locks=(False, True, True), tooltip='IK to FK')


class AXISRIGPANEL_OT_snap(bpy.types.Operator):
    bl_idname = "axis_rig_panel.snap"
    bl_label = "Snap FK / IK"
    bl_description = "Match one chain to the other without moving the limb: FK to IK, or IK to FK"
    bl_options = {'REGISTER', 'UNDO'}

    part: bpy.props.StringProperty(options={'HIDDEN'})
    side: bpy.props.StringProperty(default="L", options={'HIDDEN'})
    direction: bpy.props.StringProperty(default="FK2IK", options={'HIDDEN'})

    def execute(self, context):
        rig = main_rig(context)
        if rig is None or rigify_operator(rig, "rigify_generic_snap") is None:
            self.report({'ERROR'}, "This rig's snapping operators are not registered (is its UI script run?)")
            return {'CANCELLED'}
        with pose_mode_on(context, rig):
            if self.part == "all":
                for limb in ("arm", "leg"):
                    for side in ("L", "R"):
                        snap_limb(rig, limb, side, self.direction)
            elif self.part == "fingers":
                snap_fingers(rig, self.side, self.direction)
            else:
                snap_limb(rig, self.part, self.side, self.direction)
        refresh(context, rig)
        return {'FINISHED'}


class AXISRIGPANEL_OT_reset_pose(bpy.types.Operator):
    bl_idname = "axis_rig_panel.reset_pose"
    bl_label = "Reset Pose"
    bl_description = "Put every bone of the rig back to its rest transform"
    bl_options = {'REGISTER', 'UNDO'}

    selected_only: bpy.props.BoolProperty(name="Selected Only", default=False, options={'SKIP_SAVE'})

    def execute(self, context):
        rig = main_rig(context)
        if rig is None:
            return {'CANCELLED'}
        for pose_bone in rig.pose.bones:
            if self.selected_only and not is_selected(pose_bone):
                continue
            pose_bone.location = (0.0, 0.0, 0.0)
            pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pose_bone.rotation_axis_angle = (0.0, 0.0, 1.0, 0.0)
            pose_bone.rotation_euler = (0.0, 0.0, 0.0)
            pose_bone.scale = (1.0, 1.0, 1.0)
        refresh(context, rig)
        return {'FINISHED'}


class AXISRIGPANEL_OT_toggle_mode(bpy.types.Operator):
    bl_idname = "axis_rig_panel.toggle_mode"
    bl_label = "Pose / Object Mode"
    bl_description = "Switch the rig between Object and Pose mode"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = main_rig(context)
        if rig is None:
            return {'CANCELLED'}
        rig.hide_set(False)
        context.view_layer.objects.active = rig
        rig.select_set(True)
        mode = 'OBJECT' if rig.mode == 'POSE' else 'POSE'
        with context.temp_override(active_object=rig, object=rig, selected_objects=[rig]):
            bpy.ops.object.mode_set(mode=mode)
        return {'FINISHED'}


def limits_active(rig):
    return bool(rig) and any(c.type.startswith("LIMIT_") and not c.mute for pb in rig.pose.bones for c in pb.constraints)


class AXISRIGPANEL_OT_toggle_limits(bpy.types.Operator):
    bl_idname = "axis_rig_panel.toggle_limits"
    bl_label = "Toggle Limits"
    bl_description = "Mute or unmute every Limit constraint of the rig (location, rotation, scale, distance)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        rig = main_rig(context)
        if rig is None:
            return {'CANCELLED'}
        mute = limits_active(rig)
        for pose_bone in rig.pose.bones:
            for constraint in pose_bone.constraints:
                if constraint.type.startswith("LIMIT_"):
                    constraint.mute = mute
        refresh(context, rig)
        return {'FINISHED'}


class AXISRIGPANEL_OT_copy_pose(bpy.types.Operator):
    bl_idname = "axis_rig_panel.copy_pose"
    bl_label = "Copy Pose"
    bl_description = "Copy the pose of the selected bones"
    bl_options = {'REGISTER'}

    def execute(self, context):
        rig = main_rig(context)
        if rig is None:
            return {'CANCELLED'}
        with pose_mode_on(context, rig):
            with context.temp_override(active_object=rig, object=rig):
                bpy.ops.pose.copy()
        return {'FINISHED'}


class AXISRIGPANEL_OT_paste_pose(bpy.types.Operator):
    bl_idname = "axis_rig_panel.paste_pose"
    bl_label = "Paste Pose"
    bl_description = "Paste the copied pose onto the selected bones, optionally flipped"
    bl_options = {'REGISTER', 'UNDO'}

    flipped: bpy.props.BoolProperty(default=False, options={'HIDDEN'})

    def execute(self, context):
        rig = main_rig(context)
        if rig is None:
            return {'CANCELLED'}
        with pose_mode_on(context, rig):
            with context.temp_override(active_object=rig, object=rig):
                bpy.ops.pose.paste(flipped=self.flipped, selected_mask=True)
        return {'FINISHED'}


class AXISRIGPANEL_OT_side_mirror(bpy.types.Operator):
    bl_idname = "axis_rig_panel.side_mirror"
    bl_label = "Flip / Mirror Pose"
    bl_description = "Flip the pose between sides, or copy one side onto the other"
    bl_options = {'REGISTER', 'UNDO'}

    src: bpy.props.StringProperty(default="L", options={'HIDDEN'})
    mode: bpy.props.StringProperty(default="MIRROR", options={'HIDDEN'})

    def execute(self, context):
        rig = main_rig(context)
        if rig is None:
            return {'CANCELLED'}
        bones = rig.pose.bones
        snapshot = {pb.name: _snapshot(pb) for pb in bones}
        done = 0
        for name, data in snapshot.items():
            other = mirror_name(name)
            if other is None or other not in bones:
                continue
            if self.mode == "FLIP" or side_of(name) == self.src:
                _apply_transform(bones[other], _mirrored_transform(mirror_basis(rig, name, other), *data))
                done += 1
        refresh(context, rig)
        self.report({'INFO'}, f"{done} bones {'flipped' if self.mode == 'FLIP' else 'mirrored'}")
        return {'FINISHED'}


PROPS_PATH = "scene.axis_rig_panel_props"


def _header(layout, props, attr, title):
    box = layout.box()
    is_open = getattr(props, attr)
    row = box.row()
    row.scale_y = 1.2
    op = row.operator("wm.context_toggle", text=title, icon='TRIA_DOWN' if is_open else 'TRIA_RIGHT', depress=is_open)
    op.data_path = f"{PROPS_PATH}.{attr}"
    if is_open:
        box.separator(factor=0.3)
    return box, is_open


def _group(layout, title, icon='NONE'):
    box = layout.box()
    box.label(text=title, icon=icon)
    return box


def _row(layout):
    row = layout.row(align=False)
    row.scale_y = 1.1
    return row


def _column(layout):
    return layout.column(align=False)


def _toggle(layout, collection, text=None):
    if collection is None:
        layout.label(text="")
    else:
        layout.prop(collection, "is_visible", text=text or collection.name, toggle=True)


def _pairs(layout, collections):
    for index in range(0, len(collections), 2):
        row = _row(layout)
        _toggle(row, collections[index])
        _toggle(row, collections[index + 1] if index + 1 < len(collections) else None)


def draw_widget(layout, context, props, rig):
    parent, collections, follow = widget_collections(rig)
    if parent is None:
        return
    box, is_open = _header(layout, props, "expand_widget", "Face Widget")
    if not is_open:
        return
    row = _row(box)
    row.scale_y = 1.3
    row.prop(parent, "is_visible", text="Show Face Widget", toggle=True, icon='HIDE_OFF' if parent.is_visible else 'HIDE_ON')
    group = _group(box, "Layers", 'SHAPEKEY_DATA')
    group.enabled = parent.is_visible
    _pairs(group, collections)
    if follow:
        _row(group).prop(rig.data, '["faceWidgetFollowHead"]', text="Widget Follow Head", slider=True)


def draw_layers(layout, context, props, rig):
    box, is_open = _header(layout, props, "expand_rig", "Rig Layers")
    if not is_open:
        return
    everything = all_collections(rig.data)
    widget_parent = everything.get(FACE_WIDGET)
    board = set()
    stack = [widget_parent] if widget_parent else []
    while stack:
        collection = stack.pop()
        board.add(collection)
        stack.extend(children_of(collection, rig.data))
    usable = {c.name: c for c in everything if c not in board and not any(t in c.name for t in TECHNICAL)}
    get = usable.get

    if get("Basic Face") or get("Face Deform") or get("Gaze") or get("Tongue"):
        group = _group(box, "Head", 'USER')
        _pairs(group, [get("Basic Face"), get("Face Deform")])
        _pairs(group, [get("Gaze"), get("Tongue")])
        if "gazeFollowHead" in rig.data.keys():
            _row(group).prop(rig.data, '["gazeFollowHead"]', text="Gaze Follow Head", slider=True)

    for title, icon, left, right in (("Arms", 'VIEW_PAN', "Arm.L", "Arm.R"), ("Legs", 'BONE_DATA', "Leg.L", "Leg.R")):
        lefts = [c for n, c in usable.items() if n.startswith(left)]
        rights = [c for n, c in usable.items() if n.startswith(right)]
        if not (lefts or rights):
            continue
        group = _group(box, title, icon)
        for index in range(max(len(lefts), len(rights))):
            row = _row(group)
            _toggle(row, lefts[index] if index < len(lefts) else None)
            _toggle(row, rights[index] if index < len(rights) else None)
        if title == "Legs" and get("Toes"):
            _toggle(_row(group), get("Toes"))

    fingers = [c for c in (get("Fingers"), get("Fingers IK"), get("Fingers Detail")) if c]
    if fingers:
        _pairs(_group(box, "Fingers", 'HAND'), fingers)

    if get("Torso") or get("Torso Tweak") or get("Root"):
        group = _group(box, "Body", 'MOD_ARMATURE')
        _pairs(group, [get("Torso"), get("Torso Tweak")])
        if get("Root"):
            _row(group).prop(get("Root"), "is_visible", text="Root", toggle=True)

    known = {"Basic Face", "Face Deform", "Gaze", "Tongue", "Fingers", "Fingers IK", "Fingers Detail",
             "Toes", "Torso", "Torso Tweak", "Root"}
    others = [c for n, c in usable.items() if n not in known and not n.startswith(("Arm.", "Leg.")) and not children_of(c, rig.data)]
    if others:
        _pairs(_group(box, "Other", 'GROUP_BONE'), others)


_LABELS = (
    (re.compile(r"^IK-FK \((.+)\)$"), r"IK / FK"),
    (re.compile(r"^FK->IK \((.+)\)$"), r"FK → IK"),
    (re.compile(r"^IK->FK \((.+)\)$"), r"IK → FK"),
    (re.compile(r"^Finger IK \((.+)\)$"), r"Finger IK"),
    (re.compile(r"^Rubber Tweak \((.+)\)$"), r"Rubber Tweak"),
)


def _label(text):
    for pattern, replacement in _LABELS:
        if text and pattern.match(text):
            return pattern.sub(replacement, text)
    return text


def _draw_spec_items(layout, rig, items):
    rid = rig_id(rig)
    bones = rig.pose.bones
    for item in items:
        kind = item["kind"]
        if kind in ("row", "column", "split"):
            sub = _row(layout) if kind in ("row", "split") else _column(layout)
            _draw_spec_items(sub, rig, item["items"])
        elif kind == "separator":
            layout.separator()
        elif kind == "label":
            layout.label(text=item["text"])
        elif kind == "prop":
            owner = bones.get(item["bone"]) if item["bone"] else None
            prop_name = item["prop"][2:-2] if item["prop"].startswith('["') else item["prop"]
            if owner is None or prop_name not in owner.keys():
                continue
            text = _label(item["text"])
            if item["toggle"] and text in ("On", "Off"):
                text = "On" if owner[prop_name] else "Off"
            layout.prop(owner, item["prop"], text=text or "", slider=item["slider"], toggle=item["toggle"])
        elif kind == "operator":
            params = item["params"]
            named = [json.loads(v) if isinstance(v, str) and v.startswith("[") else [v]
                     for k, v in params.items() if k.endswith(("bones", "bone", "chain", "master", "control"))]
            if any(isinstance(n, str) and n and n != "None" and n not in bones for group in named for n in group):
                continue
            idname = f"{item['op']}_{rid}"
            module, _, name = idname.partition(".")
            if getattr(getattr(bpy.ops, module), name, None) is None:
                continue
            try:
                if item["text"] is None:
                    op = layout.operator(idname, icon=item["icon"] or 'NONE')
                else:
                    op = layout.operator(idname, text=_label(item["text"]), icon=item["icon"] or 'NONE')
            except (RuntimeError, TypeError):
                continue
            for key, value in params.items():
                try:
                    setattr(op, key, tuple(value) if isinstance(value, list) else value)
                except (AttributeError, TypeError, ValueError):
                    pass


def draw_selected(layout, context, props, rig):
    box, is_open = _header(layout, props, "expand_selected", "Selected Controls")
    if not is_open:
        return
    if context.mode != 'POSE' or context.active_object is not rig:
        box.label(text="Select controls in Pose mode", icon='INFO')
        return
    spec = control_spec(rig)
    if not spec:
        box.label(text="This rig has no control data", icon='ERROR')
        return
    selected = {pb.name for pb in (context.selected_pose_bones or [])}
    if context.active_pose_bone:
        selected.add(context.active_pose_bone.name)
    groups = [g for g in spec["groups"] if selected.intersection(g["bones"])]
    if not groups:
        box.label(text="No properties for the selection", icon='INFO')
        return
    for group in groups:
        _draw_spec_items(_column(box.box()), rig, group["items"])


def _sides(layout):
    row = layout.row(align=False)
    left, right = _column(row), _column(row)
    left.label(text="Left")
    right.label(text="Right")
    return left, right


def draw_ikfk(layout, context, props, rig):
    arms, legs = has_arms(rig), has_legs(rig)
    if not (arms or legs):
        return
    box, is_open = _header(layout, props, "expand_ikfk", "IK / FK")
    if not is_open:
        return
    pose_bones = rig.pose.bones
    fingers = has_bone(rig, "thumb.01_ik.L")
    limbs = ([("Arm", "upper_arm_parent")] if arms else []) + ([("Leg", "thigh_parent")] if legs else [])

    group = _group(box, "IK / FK Switch", 'CONSTRAINT_BONE')
    left, right = _sides(group)
    for side, column in (("L", left), ("R", right)):
        for title, parent in limbs:
            owner = pose_bones.get(f"{parent}.{side}")
            if owner is not None and "IK_FK" in owner.keys():
                column.prop(owner, '["IK_FK"]', text=f"{title} IK↔FK", slider=True)
        if fingers:
            column.label(text="Fingers")
            row = _row(column)
            for text, value in (("FK", 0.0), ("IK", 1.0)):
                op = row.operator("axis_rig_panel.set_fingers", text=text,
                                  depress=all(bone_prop(rig, f"{f}.01_ik.{side}", "FK_IK") == value for f in FINGERS))
                op.side, op.value = side, value

    group = _group(box, "Global Controls", 'OUTLINER_OB_ARMATURE')
    parents = [n for n in ARM_PARENTS + LEG_PARENTS if has_bone(rig, n)]
    all_fk = all(bone_prop(rig, n, "IK_FK") >= 0.5 for n in parents)
    row = _row(group)
    row.scale_y = 1.2
    row.operator("axis_rig_panel.toggle_ikfk_limbs_global", text="All Limbs FK" if legs else "Arms FK",
                 icon='OUTLINER_OB_ARMATURE', depress=all_fk)
    if fingers:
        all_ik = all(bone_prop(rig, f"{f}.01_ik.{s}", "FK_IK") >= 0.5 for f in FINGERS for s in ("L", "R"))
        row = _row(group)
        row.scale_y = 1.2
        op = row.operator("axis_rig_panel.set_fingers", text="All Fingers IK", icon='HAND', depress=all_ik)
        op.side, op.value = "BOTH", 0.0 if all_ik else 1.0

    group = _group(box, "Snap FK / IK", 'SNAP_ON')
    parts = ([("arm", "Arm")] if arms else []) + ([("leg", "Leg")] if legs else [])
    parts += [("fingers", "Fingers")] if fingers else []
    left, right = _sides(group)
    for side, column in (("L", left), ("R", right)):
        for part, title in parts:
            column.label(text=title)
            for direction, text in (("FK2IK", "FK → IK"), ("IK2FK", "IK → FK")):
                op = column.operator("axis_rig_panel.snap", text=text)
                op.part, op.side, op.direction = part, side, direction
    group.separator(factor=0.5)
    row = _row(group)
    row.scale_y = 1.2
    for direction, text in (("FK2IK", "All FK → IK"), ("IK2FK", "All IK → FK")):
        op = row.operator("axis_rig_panel.snap", text=text, icon='SNAP_ON')
        op.part, op.direction = "all", direction

    group = _group(box, "Stretch", 'FULLSCREEN_EXIT')
    left, right = _sides(group)
    for side, column in (("L", left), ("R", right)):
        for title, parent in limbs:
            owner = pose_bones.get(f"{parent}.{side}")
            if owner is not None and "IK_Stretch" in owner.keys():
                column.prop(owner, '["IK_Stretch"]', text=f"{title} Stretch", slider=True)


def draw_pose_tools(layout, context, props, rig):
    box, is_open = _header(layout, props, "expand_pose_tools", "Pose Tools")
    if not is_open:
        return
    group = _group(box, "Reset Pose", 'RECOVER_LAST')
    row = _row(group)
    row.operator("axis_rig_panel.reset_pose", text="All").selected_only = False
    row.operator("axis_rig_panel.reset_pose", text="Selected").selected_only = True

    group = _group(box, "Mode & Limits", 'POSE_HLT')
    in_pose = rig.mode == 'POSE'
    _row(group).operator("axis_rig_panel.toggle_mode", text="Object Mode" if in_pose else "Pose Mode",
                         icon='OBJECT_DATAMODE' if in_pose else 'POSE_HLT')
    limits_on = limits_active(rig)
    _row(group).operator("axis_rig_panel.toggle_limits", text="Limits On" if limits_on else "Limits Off",
                         icon='LOCKED' if limits_on else 'UNLOCKED', depress=limits_on)

    group = _group(box, "Copy Pose", 'COPYDOWN')
    row = _row(group)
    row.operator("axis_rig_panel.copy_pose", text="Copy", icon='COPYDOWN')
    row.operator("axis_rig_panel.paste_pose", text="Paste", icon='PASTEDOWN').flipped = False
    _row(group).operator("axis_rig_panel.paste_pose", text="Paste Flipped", icon='MOD_MIRROR').flipped = True

    group = _group(box, "Mirror", 'MOD_MIRROR')
    _row(group).operator("axis_rig_panel.side_mirror", text="Flip Left ↔ Right", icon='ARROW_LEFTRIGHT').mode = "FLIP"
    row = _row(group)
    op = row.operator("axis_rig_panel.side_mirror", text="Left → Right")
    op.src, op.mode = "L", "MIRROR"
    op = row.operator("axis_rig_panel.side_mirror", text="Right → Left")
    op.src, op.mode = "R", "MIRROR"


def draw_performance(layout, context, props):
    box, is_open = _header(layout, props, "expand_performance", "Performance")
    if not is_open:
        return
    render = context.scene.render
    row = _row(box)
    row.scale_y = 1.2
    row.operator("axis_rig_panel.toggle_simplify", text="Simplify", depress=render.use_simplify,
                 icon='CHECKBOX_HLT' if render.use_simplify else 'CHECKBOX_DEHLT')
    column = _column(box)
    column.enabled = render.use_simplify
    column.prop(render, "simplify_subdivision", text="Max Subdivision")
    column.prop(render, "simplify_child_particles", text="Child Particles", slider=True)
    note = box.column(align=True)
    note.enabled = False
    note.label(text="Viewport only. Render always", icon='INFO')
    note.label(text="uses full quality.", icon='BLANK1')


def draw_info(layout, context, props):
    box, is_open = _header(layout, props, "expand_info", "Info")
    if not is_open:
        return
    group = _group(box, f"AXIS Rig Panel {PANEL_VERSION_STR}", 'FILE_BLEND')
    state = _update_state
    if state["status"] == "idle":
        _row(group).operator("axis_rig_panel.check_update", text="Check for Updates", icon='URL')
    elif state["status"] == "checking":
        group.label(text="Checking...", icon='TIME')
    elif state["status"] == "up_to_date":
        group.label(text=f"Up to date ({'.'.join(map(str, state['remote_version']))})", icon='CHECKMARK')
        _row(group).operator("axis_rig_panel.check_update", text="Check Again", icon='FILE_REFRESH')
    elif state["status"] == "available":
        group.label(text=f"Update available: {'.'.join(map(str, state['remote_version']))}", icon='ERROR')
        _row(group).operator("axis_rig_panel.download_update", text="Update Panel", icon='IMPORT')
    else:
        group.label(text="Could not check for updates.", icon='ERROR')
        _row(group).operator("axis_rig_panel.check_update", text="Retry", icon='FILE_REFRESH')
    group = _group(box, "Links", 'URL')
    for text, icon, url in (
            ("Documentation", 'HELP', "https://www.axisproject.co/documentation"),
            ("Tutorials", 'PLAY', "https://www.youtube.com/playlist?list=PLULNUwDQZpCZnWmO3qFrcNB0OkMJqjd4Y"),
            ("Need more characters?", 'ARMATURE_DATA', "https://superhivemarket.com/creators/thecatempire"),
            ("Support", 'FUND', "mailto:contact@axisproject.co")):
        _row(group).operator("wm.url_open", text=text, icon=icon).url = url


class AXISRIGPANEL_PT_main(bpy.types.Panel):
    bl_label = "AXIS Rig"
    bl_idname = "AXISRIG_PT_panel_v2"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY

    @classmethod
    def poll(cls, context):
        return context.mode in {'OBJECT', 'POSE'}

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.axis_rig_panel_props

        row = layout.row()
        row.scale_y = 1.2
        row.prop(scene, "axis_rig_panel_rig", text="", icon='ARMATURE_DATA')
        layout.separator(factor=0.5)
        rig = main_rig(context)
        if rig is None:
            box = layout.box()
            box.label(text="Choose an AXIS rig", icon='ERROR')
            for obj in [obj for obj in context.view_layer.objects if is_axis_rig(obj)][:4]:
                _row(box).operator("axis_rig_panel.pick_rig", text=f"Use {obj.name}", icon='ARMATURE_DATA').name = obj.name
            draw_performance(layout, context, props)
            draw_info(layout, context, props)
            return

        draw_widget(layout, context, props, rig)
        draw_layers(layout, context, props, rig)
        draw_ikfk(layout, context, props, rig)
        draw_pose_tools(layout, context, props, rig)
        draw_selected(layout, context, props, rig)
        draw_performance(layout, context, props)
        draw_info(layout, context, props)


class AXISRIGPANEL_OT_pick_rig(bpy.types.Operator):
    bl_idname = "axis_rig_panel.pick_rig"
    bl_label = "Use This Rig"
    bl_description = "Control this AXIS rig with the panel"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if not is_axis_rig(obj):
            return {'CANCELLED'}
        context.scene.axis_rig_panel_rig = obj
        return {'FINISHED'}


class AXISRIGPANEL_OT_CheckUpdate(bpy.types.Operator):
    bl_idname = "axis_rig_panel.check_update"
    bl_label = "Check for Updates"
    bl_description = "Check for a newer version of the AXIS Panel"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        _update_state["status"] = "checking"
        _update_state["remote_version"] = None

        def _check():
            try:
                with _urllib_request.urlopen(_VERSION_URL, timeout=8, context=_ssl_ctx) as response:
                    data = json.loads(response.read().decode())
                remote = tuple(data["version"])
                _update_state["remote_version"] = remote
                _update_state["status"] = "available" if remote > PANEL_VERSION else "up_to_date"
            except Exception:
                _update_state["status"] = "error"

        threading.Thread(target=_check, daemon=True).start()
        bpy.app.timers.register(_redraw_until_checked, first_interval=0.5)
        return {'FINISHED'}


def _redraw_until_checked():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    return 0.5 if _update_state["status"] == "checking" else None


class AXISRIGPANEL_OT_DownloadUpdate(bpy.types.Operator):
    bl_idname = "axis_rig_panel.download_update"
    bl_label = "Update Panel"
    bl_description = "Download and install the latest AXIS Panel from GitHub"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        try:
            with _urllib_request.urlopen(_PANEL_RAW_URL, timeout=15, context=_ssl_ctx) as response:
                source = response.read().decode("utf-8")
        except Exception as error:
            self.report({'ERROR'}, f"Download failed: {error}")
            return {'CANCELLED'}
        text = bpy.data.texts.get(TEXT_NAME)
        if text is None:
            self.report({'ERROR'}, f"{TEXT_NAME} text block not found.")
            return {'CANCELLED'}
        text.clear()
        text.write(source)
        try:
            exec(compile(source, TEXT_NAME, "exec"), {"__name__": "__main__"})
        except Exception as error:
            self.report({'ERROR'}, f"Execution error: {error}")
            return {'CANCELLED'}
        _update_state["status"] = "idle"
        _update_state["remote_version"] = None
        self.report({'INFO'}, "AXIS Panel updated.")
        return {'FINISHED'}


classes = [
    AXISRIGPANEL_Props,
    AXISRIGPANEL_PT_main,
    AXISRIGPANEL_OT_ToggleSimplify,
    AXISRIGPANEL_OT_limbs_ikfk,
    AXISRIGPANEL_OT_fingers,
    AXISRIGPANEL_OT_snap,
    AXISRIGPANEL_OT_reset_pose,
    AXISRIGPANEL_OT_toggle_mode,
    AXISRIGPANEL_OT_toggle_limits,
    AXISRIGPANEL_OT_copy_pose,
    AXISRIGPANEL_OT_paste_pose,
    AXISRIGPANEL_OT_side_mirror,
    AXISRIGPANEL_OT_pick_rig,
    AXISRIGPANEL_OT_CheckUpdate,
    AXISRIGPANEL_OT_DownloadUpdate,
]


def _registered(cls):
    if issubclass(cls, bpy.types.Panel):
        return getattr(bpy.types, cls.bl_idname, None)
    if issubclass(cls, bpy.types.Operator):
        module, _, name = cls.bl_idname.partition(".")
        return getattr(bpy.types, f"{module.upper()}_OT_{name}", None)
    return getattr(bpy.types, cls.__name__, None)


def register():
    for cls in classes:
        previous = _registered(cls)
        if previous is not None:
            try:
                bpy.utils.unregister_class(previous)
            except RuntimeError:
                pass
        bpy.utils.register_class(cls)
    bpy.types.Scene.axis_rig_panel_props = bpy.props.PointerProperty(type=AXISRIGPANEL_Props)
    bpy.types.Scene.axis_rig_panel_rig = bpy.props.PointerProperty(
        name="AXIS Rig", description="The AXIS rig this panel controls",
        type=bpy.types.Object, poll=lambda self, obj: is_axis_rig(obj))
    for handler in [h for h in bpy.app.handlers.load_post if getattr(h, "__name__", "") == "_adapt_on_load"]:
        bpy.app.handlers.load_post.remove(handler)
    bpy.app.handlers.load_post.append(_adapt_on_load)
    try:
        adapt_visibility_drivers()
    except AttributeError:
        pass


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for handler in [h for h in bpy.app.handlers.load_post if getattr(h, "__name__", "") == "_adapt_on_load"]:
        bpy.app.handlers.load_post.remove(handler)
    for attr in ("axis_rig_panel_rig", "axis_rig_panel_props"):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)


def _register_after_update():
    if getattr(bpy.types, "AXIS_RIG_PANEL_OT_download_update", None) is not AXISRIGPANEL_OT_DownloadUpdate:
        register()
    return None


if __name__ == "__main__":
    if hasattr(bpy.types, "AXIS_RIG_PANEL_OT_download_update"):
        bpy.app.timers.register(_register_after_update, first_interval=0.0, persistent=True)
    else:
        register()
