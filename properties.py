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


def _show(st, index):
    """Move to *index* and display it, without re-entering the update callbacks."""
    seq = session.get_sequence()
    if not (seq and seq.count):
        return
    lo, hi = session.active_range(st, seq)
    index = max(lo, min(index, hi))
    st["frame_index"] = index
    st["frame_number"] = seq.frames[index]
    session.apply_frame()


def _frame_index_changed(self, context):
    # IntProperty has no dynamic maximum, so the bounds are enforced here. The
    # in/out range is the bound when it is active, which is what keeps scrubbing
    # and stepping from leaving the range the user asked to review.
    _show(self, self.frame_index)


def _frame_number_changed(self, context):
    """Scrubbing is done in real frame numbers; snap onto a frame that exists."""
    seq = session.get_sequence()
    if not (seq and seq.count):
        return
    lo, hi = session.active_range(self, seq)
    number = max(seq.frames[lo], min(self.frame_number, seq.frames[hi]))
    _show(self, seq.index_of(number))


def _range_changed(self, context):
    """Tightening the range around the playhead should pull the playhead in."""
    _show(self, self.frame_index)


def _playing_changed(self, context):
    if self.playing:
        seq = session.get_sequence()
        # Restarting from the out point should roll back to the in point.
        if seq and seq.count:
            lo, hi = session.active_range(self, seq)
            if self.loop_mode == 'ONCE' and self.frame_index >= hi:
                _show(self, lo)
        session.start_clock()


class BBAV_Settings(PropertyGroup):

    filepath: StringProperty(
        name="Sequence",
        description="A representative file of the sequence currently loaded",
        subtype='FILE_PATH',
        default="",
    )
    seq_label: StringProperty(name="Label", default="")
    # Name of the image datablock this session drives. Any Image Editor showing
    # it counts as a viewer, which is how the render window can be adopted.
    image_name: StringProperty(name="Image", default="")

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
    use_scene_fps: BoolProperty(
        name="Scene FPS",
        description="Play at the scene's render frame rate. "
                    "Turn off to set a rate just for reviewing",
        default=True,
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
    sync_scene_frame: BoolProperty(
        name="Follow Timeline",
        description="Scrubbing the scene timeline scrubs the viewer, matching frame "
                    "numbers. One-way: playback here does not move the scene frame, "
                    "which is what keeps it from evaluating the scene on every frame",
        default=True,
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
        description="Restrict playback and scrubbing to a sub-range of the sequence",
        default=False,
        update=_range_changed,
    )
    range_start: IntProperty(name="In", default=0, min=0, update=_range_changed)
    range_end: IntProperty(name="Out", default=0, min=0, update=_range_changed)

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
        try:
            del bpy.types.WindowManager.bb_animviewer
        except Exception:
            pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
