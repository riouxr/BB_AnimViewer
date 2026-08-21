# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – session settings
#
#  Lives on the WindowManager: a flipbook session is a property of the running
#  Blender, not of the .blend, and should not dirty the file or get saved into it.
# ─────────────────────────────────────────────────────────────────────────────

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty,
)
from bpy.types import PropertyGroup

from . import session


def _frame_index_changed(self, context):
    # IntProperty has no dynamic maximum, so the range is clamped here instead.
    # Assigning through the ID-property dict deliberately skips these callbacks,
    # which is what keeps index and number from bouncing off each other.
    seq = session.get_sequence()
    if seq and seq.count:
        clamped = max(0, min(self.frame_index, seq.count - 1))
        if clamped != self.frame_index:
            self["frame_index"] = clamped
        self["frame_number"] = seq.frames[clamped]
    session.apply_frame()


def _frame_number_changed(self, context):
    """Scrubbing is done in real frame numbers; snap onto a frame that exists."""
    seq = session.get_sequence()
    if not (seq and seq.count):
        return
    number = max(seq.first, min(self.frame_number, seq.last))
    index = seq.index_of(number)
    self["frame_index"] = index
    self["frame_number"] = seq.frames[index]
    session.apply_frame()


def _playing_changed(self, context):
    if self.playing:
        seq = session.get_sequence()
        # Restarting from the out point should roll back to the in point.
        if seq and seq.count:
            lo, hi = session.active_range(self, seq)
            if self.loop_mode == 'ONCE' and self.frame_index >= hi:
                self["frame_index"] = lo
                session.apply_frame()
        session.start_clock()


class BBAV_Settings(PropertyGroup):

    filepath: StringProperty(
        name="Sequence",
        description="A representative file of the sequence currently loaded",
        subtype='FILE_PATH',
        default="",
    )
    seq_label: StringProperty(name="Label", default="")

    # ── position ────────────────────────────────────────────────────────────
    frame_index: IntProperty(
        name="Frame",
        description="Position within the sequence. Holes on disk are skipped",
        default=0, min=0,
        update=_frame_index_changed,
    )
    frame_number: IntProperty(
        name="Frame",
        description="The frame number on disk. Drag to scrub the sequence",
        default=0,
        update=_frame_number_changed,
    )
    frame_count: IntProperty(name="Count", default=0, min=0)
    frame_first: IntProperty(name="First", default=0)
    frame_last: IntProperty(name="Last", default=0)

    # ── transport ───────────────────────────────────────────────────────────
    playing: BoolProperty(
        name="Play",
        description="Play the sequence",
        default=False,
        update=_playing_changed,
    )
    fps: FloatProperty(
        name="FPS",
        description="Playback rate in frames per second",
        default=24.0, min=0.1, max=240.0, soft_min=1.0, soft_max=60.0,
        precision=2,
    )
    loop_mode: EnumProperty(
        name="Loop",
        description="What happens at the end of the range",
        items=[
            ('LOOP', "Loop", "Jump back to the in point and keep going", 'FILE_REFRESH', 0),
            ('PINGPONG', "Ping-Pong", "Reverse direction at each end", 'ARROW_LEFTRIGHT', 1),
            ('ONCE', "Once", "Stop at the out point", 'TRIA_RIGHT', 2),
        ],
        default='LOOP',
    )
    drop_frames: BoolProperty(
        name="Drop Frames",
        description="Hold the frame rate by skipping frames when playback cannot keep up. "
                    "Turn off to show every frame instead, however slow",
        default=True,
    )
    ping_dir: IntProperty(name="Ping Direction", default=1, options={'HIDDEN'})

    # ── in / out ────────────────────────────────────────────────────────────
    use_range: BoolProperty(
        name="Use In/Out",
        description="Restrict playback to a sub-range of the sequence",
        default=False,
    )
    range_start: IntProperty(name="In", default=0, min=0)
    range_end: IntProperty(name="Out", default=0, min=0)

    # ── display ─────────────────────────────────────────────────────────────
    show_channels: BoolProperty(name="Channels", default=True)
    show_info: BoolProperty(name="Sequence Info", default=False)


classes = (BBAV_Settings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.bb_animviewer = bpy.props.PointerProperty(type=BBAV_Settings)


def unregister():
    if hasattr(bpy.types.WindowManager, "bb_animviewer"):
        del bpy.types.WindowManager.bb_animviewer
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
