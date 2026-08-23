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
from bpy.types import Menu, Panel, UIList

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


def _draw_transport(layout, wm, st, seq):
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

    # One control, not two: a real slider showing the real frame number, hard
    # limited to the range. Its bounds are re-declared by refresh_scrub whenever
    # the sequence or the in/out range changes, which is what stops a drag from
    # running past the last frame or into negatives.
    row = layout.row(align=True)
    row.scale_y = 1.2
    row.prop(wm, "bbav_frame", text="Frame", slider=True)


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

        _draw_transport(layout, context.window_manager, st, seq)

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
        # Closing lives in the Render menu (bb_animviewer.close there too) —
        # not duplicated here, since closing the popup window is one click on
        # its own titlebar anyway.


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

        # Drawn by Blender rather than as our own buttons on purpose.
        # display_channels is a dynamic enum: which items exist depends on what
        # the current buffer actually holds, so an EXR pass with no alpha offers
        # no Alpha, and only a real Z buffer offers Z. Python cannot read that
        # resolved list — bl_rna reports all seven items regardless — so drawing
        # our own buttons meant offering ones that raise on click. Letting
        # Blender expand the enum shows exactly what is available, and re-checks
        # every redraw as you switch passes.
        grid = layout.grid_flow(row_major=True, columns=2, align=True)
        grid.prop(space, "display_channels", expand=True)

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


class BBAV_UL_sequences(UIList):
    """One row per version found alongside the sequence currently open."""

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            split = layout.split(factor=0.6)
            split.label(text=item.name,
                       icon='FILE_IMAGE' if item.is_still else 'RENDERLAYERS')
            row = split.row()
            row.alignment = 'RIGHT'
            if item.missing:
                row.label(text="", icon='ERROR')
            row.label(text=item.range_text)
        else:
            layout.label(text=item.name)


class BBAV_PT_list(Panel):
    bl_idname = "BBAV_PT_list"
    bl_label = "Sequence List"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Viewer"
    # No DEFAULT_CLOSED: expanded by default, unlike Sequence Info below it.

    @classmethod
    def poll(cls, context):
        return _in_viewer(context)

    def draw(self, context):
        layout = self.layout
        st = context.window_manager.bb_animviewer
        seq = session.get_sequence()
        if seq is None:
            return

        layout.template_list(
            "BBAV_UL_sequences", "",
            st, "sequence_list",
            st, "list_index",
            rows=6,
        )
        layout.operator("bb_animviewer.reload", text="Refresh List", icon='FILE_REFRESH')


class BBAV_PT_info(Panel):
    bl_idname = "BBAV_PT_info"
    bl_label = "Sequence Info"
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
    BBAV_UL_sequences,
    BBAV_PT_list,
    BBAV_PT_info,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_render.append(draw_render_menu)
    bpy.types.IMAGE_HT_header.append(draw_image_header)


def unregister():
    # Tolerant teardown. If two copies of this addon are ever live at once (a
    # dev copy on sys.path next to the installed extension, say) the first one
    # out takes the shared bl_idnames with it, and a strict unregister would
    # then raise and leave the second half torn down.
    for owner, func in ((bpy.types.IMAGE_HT_header, draw_image_header),
                        (bpy.types.TOPBAR_MT_render, draw_render_menu)):
        try:
            owner.remove(func)
        except Exception:
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
