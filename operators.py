# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – operators
# ─────────────────────────────────────────────────────────────────────────────

import os

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator

from . import sequence as seqmod
from . import session


def _viewer_active(context):
    """A viewer session exists somewhere. Used by the Render menu entries."""
    return session.viewer_open() and bool(session.get_sequence())


def _viewer_focused(context):
    """The area being acted on is the viewer's own image editor.

    Transport operators are bound to plain keys (space, arrows, r/g/b/a/z) in the
    Image keymap, so they must stay inert in any other Image Editor the user has
    open — otherwise the viewer would hijack keys across the whole session.
    """
    if not _viewer_active(context):
        return False
    space = getattr(context, "space_data", None)
    if space is None or space.type != 'IMAGE_EDITOR':
        return False
    return session.is_viewer_space(space)


def _target_space(op, context):
    """The Image Editor to adopt, when the operator was asked to open in place."""
    if not getattr(op, "here", False):
        return None
    space = getattr(context, "space_data", None)
    if space is not None and space.type == 'IMAGE_EDITOR':
        return space
    return None


# ── opening ─────────────────────────────────────────────────────────────────

class BBAV_OT_open_sequence(Operator):
    """Pick an image sequence and open it in the BB AnimViewer window"""
    bl_idname = "bb_animviewer.open_sequence"
    bl_label = "Open Sequence..."
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_image: BoolProperty(default=True, options={'HIDDEN'})
    filter_folder: BoolProperty(default=True, options={'HIDDEN'})
    here: BoolProperty(
        name="Open Here",
        description="Take over this image editor instead of opening a new window",
        default=False, options={'SKIP_SAVE'},
    )

    def invoke(self, context, event):
        st = context.window_manager.bb_animviewer
        if st.filepath:
            self.filepath = st.filepath
        else:
            directory = seqmod.resolve_render_output(context.scene)
            self.filepath = os.path.join(directory, "") if directory else ""
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        path = bpy.path.abspath(self.filepath)
        if os.path.isdir(path):
            found = seqmod.scan(path)
            if not found:
                self.report({'ERROR'}, "No image sequence in %s" % path)
                return {'CANCELLED'}
            seq = found[0]
        else:
            seq = seqmod.from_file(path)
            if seq is None:
                self.report({'ERROR'}, "Not a readable image: %s" % os.path.basename(path))
                return {'CANCELLED'}

        index = seq.index_of(_number_of(path)) if not seq.is_still else 0
        error = session.open_viewer(context, seq, index, space=_target_space(self, context))
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        self.report({'INFO'}, seq.label())
        return {'FINISHED'}


def _number_of(path):
    match = seqmod.SEQ_RE.match(os.path.basename(path))
    return int(match.group("num")) if match else 0


class BBAV_OT_open_render_output(Operator):
    """Open the scene's render output folder in the BB AnimViewer window"""
    bl_idname = "bb_animviewer.open_render_output"
    bl_label = "Open Render Output"
    bl_options = {'REGISTER'}

    here: BoolProperty(
        name="Open Here",
        description="Take over this image editor instead of opening a new window",
        default=False, options={'SKIP_SAVE'},
    )

    def execute(self, context):
        directory = seqmod.resolve_render_output(context.scene)
        if not directory or not os.path.isdir(directory):
            self.report({'ERROR'}, "Render output folder does not exist yet: %s" % (directory or "unset"))
            return {'CANCELLED'}

        found = seqmod.scan(directory)
        if not found:
            self.report({'ERROR'}, "No rendered frames in %s" % directory)
            return {'CANCELLED'}

        error = session.open_viewer(context, found[0], 0, space=_target_space(self, context))
        if error:
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        self.report({'INFO'}, found[0].label())
        return {'FINISHED'}


class BBAV_OT_reload(Operator):
    """Re-scan the folder to pick up frames rendered since the viewer was opened"""
    bl_idname = "bb_animviewer.reload"
    bl_label = "Reload"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _viewer_active(context)

    def execute(self, context):
        st = context.window_manager.bb_animviewer
        old = session.get_sequence()
        number = session.current_number()

        fresh = seqmod.from_file(st.filepath)
        if fresh is None or not fresh.count:
            self.report({'WARNING'}, "Sequence no longer on disk")
            return {'CANCELLED'}

        session.set_sequence(fresh)
        st.frame_count = fresh.count
        st.frame_first = fresh.first
        st.frame_last = fresh.last
        st.seq_label = fresh.label()
        if st.range_end >= old.count - 1 or st.range_end == 0:
            st.range_end = fresh.count - 1
        st["frame_index"] = fresh.index_of(number)
        from . import properties
        properties.refresh_scrub()

        image = session.viewer_space().image
        if image:
            image.reload()
        session.apply_frame()
        self.report({'INFO'}, fresh.label())
        return {'FINISHED'}


class BBAV_OT_close(Operator):
    """Close the BB AnimViewer window"""
    bl_idname = "bb_animviewer.close"
    bl_label = "Close Viewer"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return session.viewer_open()

    def execute(self, context):
        session.close_viewer(context)
        return {'FINISHED'}


# ── transport ───────────────────────────────────────────────────────────────

class BBAV_OT_play(Operator):
    """Start or stop playback"""
    bl_idname = "bb_animviewer.play"
    bl_label = "Play / Pause"
    bl_options = {'REGISTER'}

    mode: EnumProperty(
        items=[('TOGGLE', "Toggle", ""), ('PLAY', "Play", ""), ('STOP', "Stop", "")],
        default='TOGGLE', options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _viewer_focused(context)

    def execute(self, context):
        st = context.window_manager.bb_animviewer
        if self.mode == 'TOGGLE':
            st.playing = not st.playing
        else:
            st.playing = (self.mode == 'PLAY')
        return {'FINISHED'}


class BBAV_OT_step(Operator):
    """Step the viewer by a number of frames"""
    bl_idname = "bb_animviewer.step"
    bl_label = "Step"
    bl_options = {'REGISTER'}

    delta: IntProperty(default=1, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _viewer_focused(context)

    def execute(self, context):
        st = context.window_manager.bb_animviewer
        seq = session.get_sequence()
        st.playing = False
        lo, hi = session.active_range(st, seq)
        index = st.frame_index + self.delta
        # Stepping past an end wraps, the way a flipbook player does.
        if index > hi:
            index = lo
        elif index < lo:
            index = hi
        st.frame_index = index
        return {'FINISHED'}


class BBAV_OT_jump(Operator):
    """Jump to the start or end of the range"""
    bl_idname = "bb_animviewer.jump"
    bl_label = "Jump"
    bl_options = {'REGISTER'}

    to: EnumProperty(
        items=[('START', "Start", ""), ('END', "End", "")],
        default='START', options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _viewer_focused(context)

    def execute(self, context):
        st = context.window_manager.bb_animviewer
        lo, hi = session.active_range(st, session.get_sequence())
        st.playing = False
        st.frame_index = lo if self.to == 'START' else hi
        return {'FINISHED'}


class BBAV_OT_set_range(Operator):
    """Set the in or out point to the current frame, or clear the range"""
    bl_idname = "bb_animviewer.set_range"
    bl_label = "Set Range"
    bl_options = {'REGISTER'}

    edge: EnumProperty(
        items=[('IN', "In", ""), ('OUT', "Out", ""), ('CLEAR', "Clear", "")],
        default='IN', options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _viewer_focused(context)

    def execute(self, context):
        st = context.window_manager.bb_animviewer
        seq = session.get_sequence()
        if self.edge == 'CLEAR':
            st.use_range = False
            st.range_start = 0
            st.range_end = seq.count - 1
        elif self.edge == 'IN':
            st.range_start = st.frame_index
            st.use_range = True
        else:
            st.range_end = st.frame_index
            st.use_range = True
        return {'FINISHED'}


# ── display ─────────────────────────────────────────────────────────────────

class BBAV_OT_channel(Operator):
    """Show a single channel, fcheck style"""
    bl_idname = "bb_animviewer.channel"
    bl_label = "Display Channel"
    bl_options = {'REGISTER'}

    channel: EnumProperty(
        items=[(c, c.title(), "") for c in
               ("COLOR_ALPHA", "COLOR", "ALPHA", "Z_BUFFER", "RED", "GREEN", "BLUE")],
        default='COLOR', options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _viewer_focused(context)

    def execute(self, context):
        space = session.viewer_space()
        if space is None:
            return {'CANCELLED'}
        # Pressing the key of the channel already shown returns to full colour,
        # so r-r toggles rather than sticking.
        target = 'COLOR' if space.display_channels == self.channel else self.channel
        try:
            space.display_channels = target
        except TypeError:
            # display_channels is a dynamic enum — an EXR pass carrying no alpha
            # does not offer Alpha, and only a real Z buffer offers Z. Pressing
            # the key for one of those is a no-op, not an error.
            self.report({'INFO'}, "%s not available for this image"
                                  % target.replace("_", " ").title())
            return {'CANCELLED'}
        session.redraw()
        return {'FINISHED'}


class BBAV_OT_cycle_loop(Operator):
    """Cycle through loop, ping-pong and play-once"""
    bl_idname = "bb_animviewer.cycle_loop"
    bl_label = "Cycle Loop Mode"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _viewer_focused(context)

    def execute(self, context):
        st = context.window_manager.bb_animviewer
        order = ('LOOP', 'PINGPONG', 'ONCE')
        st.loop_mode = order[(order.index(st.loop_mode) + 1) % len(order)]
        self.report({'INFO'}, "Loop: %s" % st.loop_mode.title())
        return {'FINISHED'}


class BBAV_OT_fit_view(Operator):
    """Fit the image to the viewer window"""
    bl_idname = "bb_animviewer.fit_view"
    bl_label = "Fit View"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return session.viewer_open()

    def execute(self, context):
        session.fit_view()
        return {'FINISHED'}


classes = (
    BBAV_OT_open_sequence,
    BBAV_OT_open_render_output,
    BBAV_OT_reload,
    BBAV_OT_close,
    BBAV_OT_play,
    BBAV_OT_step,
    BBAV_OT_jump,
    BBAV_OT_set_range,
    BBAV_OT_channel,
    BBAV_OT_cycle_loop,
    BBAV_OT_fit_view,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
