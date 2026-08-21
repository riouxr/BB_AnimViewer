# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – Render menu entry and the viewer sidebar
#
#  The panels appear in two places: any Image Editor hosting the session, and
#  the window Blender opens for a render — so the frames you just rendered can
#  be reviewed without closing that window first. A plain Image Editor the user
#  is working in is left alone.
# ─────────────────────────────────────────────────────────────────────────────

import os

import bpy
from bpy.types import Menu, Panel

from . import exr
from . import session


def _in_viewer(context):
    """This editor is hosting the flipbook session."""
    space = context.space_data
    return space and space.type == 'IMAGE_EDITOR' and session.is_viewer_space(space)


def _is_render_window(context):
    """This editor is showing a render result, ours or Blender's own."""
    space = context.space_data
    if not space or space.type != 'IMAGE_EDITOR' or space.image is None:
        return False
    return space.image.type in {'RENDER_RESULT', 'COMPOSITING'}


def _panel_visible(context):
    return _in_viewer(context) or _is_render_window(context)


# ── Render menu ─────────────────────────────────────────────────────────────

class BBAV_MT_render_menu(Menu):
    bl_idname = "BBAV_MT_render_menu"
    bl_label = "BB AnimViewer"

    def draw(self, context):
        layout = self.layout
        layout.operator("bb_animviewer.open_render_output", icon='RENDER_ANIMATION')
        layout.operator("bb_animviewer.open_sequence", icon='FILE_FOLDER')
        layout.separator()
        layout.operator("bb_animviewer.reload", icon='FILE_REFRESH')
        layout.operator("bb_animviewer.close", icon='X')


def draw_render_menu(self, context):
    self.layout.separator()
    self.layout.menu(BBAV_MT_render_menu.bl_idname, icon='SEQUENCE')


# ── transport ───────────────────────────────────────────────────────────────

def _draw_adopt(layout):
    """Shown in a render window that has not been turned into a flipbook yet."""
    col = layout.column(align=True)
    col.scale_y = 1.2
    props = col.operator("bb_animviewer.open_render_output",
                         text="Review Rendered Frames", icon='SEQUENCE')
    props.here = True
    props = col.operator("bb_animviewer.open_sequence",
                         text="Open Sequence...", icon='FILE_FOLDER')
    props.here = True

    col = layout.column(align=True)
    col.scale_y = 0.85
    col.label(text="Plays the frames written to disk,")
    col.label(text="in this window.")

    layout.separator()
    layout.operator("bb_animviewer.open_render_output",
                    text="Open in New Window", icon='WINDOW').here = False


def _draw_transport(layout, st, seq):
    row = layout.row(align=True)
    row.scale_y = 1.35
    row.operator("bb_animviewer.jump", text="", icon='REW').to = 'START'
    row.operator("bb_animviewer.step", text="", icon='FRAME_PREV').delta = -1
    if st.playing:
        row.operator("bb_animviewer.play", text="", icon='PAUSE', depress=True).mode = 'TOGGLE'
    else:
        row.operator("bb_animviewer.play", text="", icon='PLAY').mode = 'TOGGLE'
    row.operator("bb_animviewer.step", text="", icon='FRAME_NEXT').delta = 1
    row.operator("bb_animviewer.jump", text="", icon='FF').to = 'END'

    lo, hi = session.active_range(st, seq)
    span = max(1, hi - lo)
    # A plain number field, not a slider: an IntProperty's soft range is fixed at
    # registration, so a slider bar would be meaningless for an arbitrary frame
    # range. The bar underneath carries the position instead.
    layout.prop(st, "frame_number", text="Frame")
    if hasattr(layout, "progress"):
        factor = max(0.0, min(1.0, (st.frame_index - lo) / span))
        layout.progress(factor=factor, type='BAR',
                        text="%d / %d" % (st.frame_index - lo + 1, hi - lo + 1))
    else:
        info = layout.row()
        info.alignment = 'CENTER'
        info.label(text="%d / %d" % (st.frame_index - lo + 1, hi - lo + 1))


class BBAV_PT_transport(Panel):
    bl_idname = "BBAV_PT_transport"
    bl_label = "Playback"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Viewer"

    @classmethod
    def poll(cls, context):
        return _panel_visible(context)

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.bb_animviewer
        seq = session.get_sequence()

        if not _in_viewer(context):
            _draw_adopt(layout)
            return

        if seq is None or not seq.count:
            layout.label(text="No sequence loaded", icon='INFO')
            layout.operator("bb_animviewer.open_sequence", icon='FILE_FOLDER')
            return

        _draw_transport(layout, st, seq)

        layout.separator()
        col = layout.column(align=True)
        col.prop(st, "use_scene_fps")
        sub = col.row(align=True)
        if st.use_scene_fps:
            sub.enabled = False
            sub.label(text="%.4g fps (scene)" % session.scene_fps())
        else:
            sub.prop(st, "fps")
        col.prop(st, "loop_mode", text="")

        col = layout.column(align=True)
        col.prop(st, "drop_frames")
        col.prop(st, "sync_scene_frame")

        layout.separator()
        row = layout.row(align=True)
        row.operator("bb_animviewer.reload", icon='FILE_REFRESH')
        row.operator("bb_animviewer.fit_view", text="Fit", icon='ZOOM_ALL')
        layout.operator("bb_animviewer.close", text="Close Viewer", icon='X')


class BBAV_PT_range(Panel):
    bl_idname = "BBAV_PT_range"
    bl_parent_id = "BBAV_PT_transport"
    bl_label = "In / Out"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Viewer"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _in_viewer(context)

    def draw_header(self, context):
        self.layout.prop(context.window_manager.bb_animviewer, "use_range", text="")

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.bb_animviewer
        seq = session.get_sequence()
        if seq is None or not seq.count:
            return

        layout.active = st.use_range
        row = layout.row(align=True)
        row.operator("bb_animviewer.set_range", text="Set In").edge = 'IN'
        row.operator("bb_animviewer.set_range", text="Set Out").edge = 'OUT'

        col = layout.column(align=True)
        col.prop(st, "range_start", text="In")
        col.prop(st, "range_end", text="Out")

        lo, hi = session.active_range(st, seq)
        layout.label(text="Frames %d - %d" % (seq.frames[lo], seq.frames[hi]))
        layout.operator("bb_animviewer.set_range", text="Clear", icon='X').edge = 'CLEAR'


# ── channels and layers ─────────────────────────────────────────────────────

_CHANNEL_KEYS = (
    ('COLOR', "RGB", 'IMAGE_RGB'),
    ('COLOR_ALPHA', "RGBA", 'IMAGE_RGB_ALPHA'),
    ('ALPHA', "Alpha", 'IMAGE_ALPHA'),
    ('Z_BUFFER', "Z", 'IMAGE_ZDEPTH'),
)


class BBAV_PT_channels(Panel):
    bl_idname = "BBAV_PT_channels"
    bl_label = "Channels"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Viewer"

    @classmethod
    def poll(cls, context):
        return _in_viewer(context)

    def draw(self, context):
        layout = self.layout
        space = context.space_data
        image = space.image
        if image is None:
            return

        col = layout.column(align=True)
        row = col.row(align=True)
        for value, label, icon in _CHANNEL_KEYS:
            row.operator("bb_animviewer.channel", text=label, icon=icon,
                         depress=(space.display_channels == value)).channel = value

        row = col.row(align=True)
        for value, label in (('RED', "R"), ('GREEN', "G"), ('BLUE', "B")):
            row.operator("bb_animviewer.channel", text=label,
                         depress=(space.display_channels == value)).channel = value

        # Blender's own layer/pass/view dropdowns. These are the only way to
        # switch multilayer passes: ImageUser.multilayer_* is read-only to
        # Python, so there is nothing to drive them with from an operator.
        #
        # image.type only flips to MULTILAYER once the editor has drawn the
        # frame at least once, so the EXR header is consulted as well — without
        # it the dropdowns would be missing on the very first draw.
        if image.type == 'MULTILAYER' or exr.is_multilayer(session.current_path()):
            layout.separator()
            layout.label(text="EXR Layer / Pass:")
            layout.template_image_layers(image, space.image_user)


class BBAV_PT_color(Panel):
    bl_idname = "BBAV_PT_color"
    bl_label = "Color Management"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Viewer"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _in_viewer(context)

    def draw(self, context):
        layout = self.layout
        view = context.scene.view_settings
        # The scene's own view settings — the same datablock as Render
        # Properties > Color Management, so what you see here is what the render
        # was graded with.
        col = layout.column(align=True)
        col.prop(view, "view_transform", text="")
        col.prop(view, "look", text="")
        col = layout.column(align=True)
        col.prop(view, "exposure")
        col.prop(view, "gamma")
        col = layout.column(align=True)
        col.scale_y = 0.85
        col.label(text="Shared with Render Properties.")


class BBAV_PT_info(Panel):
    bl_idname = "BBAV_PT_info"
    bl_label = "Sequence"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Viewer"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return _in_viewer(context)

    def draw(self, context):
        layout = self.layout
        seq = session.get_sequence()
        if seq is None:
            return

        box = layout.box()
        box.label(text=seq.name, icon='SEQUENCE')
        col = box.column(align=True)
        col.scale_y = 0.85
        if not seq.is_still:
            col.label(text="Range: %d - %d" % (seq.first, seq.last))
            col.label(text="Frames: %d" % seq.count)
            if seq.missing:
                col.label(text="Missing: %d" % seq.missing, icon='ERROR')
        col.label(text=seq.directory)

        path = session.current_path()
        if path.lower().endswith(".exr"):
            passes = exr.summary(path)
            if passes:
                layout.separator()
                layout.label(text="EXR contents:")
                box = layout.box()
                col = box.column(align=True)
                col.scale_y = 0.85
                for layer, names in passes:
                    col.label(text=layer, icon='RENDERLAYERS')
                    for name in names:
                        col.label(text="    " + (name or "(rgba)"))


# ── viewer window header ────────────────────────────────────────────────────

def draw_image_header(self, context):
    if not _in_viewer(context):
        return
    st = context.window_manager.bb_animviewer
    seq = session.get_sequence()
    if seq is None or not seq.count:
        return

    layout = self.layout
    layout.separator()
    row = layout.row(align=True)
    row.operator("bb_animviewer.jump", text="", icon='REW').to = 'START'
    row.operator("bb_animviewer.step", text="", icon='FRAME_PREV').delta = -1
    row.operator("bb_animviewer.play", text="", icon='PAUSE' if st.playing else 'PLAY',
                 depress=st.playing).mode = 'TOGGLE'
    row.operator("bb_animviewer.step", text="", icon='FRAME_NEXT').delta = 1
    row.operator("bb_animviewer.jump", text="", icon='FF').to = 'END'
    layout.label(text="%d" % session.current_number())


classes = (
    BBAV_MT_render_menu,
    BBAV_PT_transport,
    BBAV_PT_range,
    BBAV_PT_channels,
    BBAV_PT_color,
    BBAV_PT_info,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_render.append(draw_render_menu)
    bpy.types.IMAGE_HT_header.append(draw_image_header)


def unregister():
    bpy.types.IMAGE_HT_header.remove(draw_image_header)
    bpy.types.TOPBAR_MT_render.remove(draw_render_menu)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
