# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – session settings
#
#  Lives on the WindowManager: a flipbook session is a property of the running
#  Blender, not of the .blend, and should not dirty the file or get saved into it.
#
#  The scrub control is a special case. An IntProperty fixes min/max at
#  registration time, so clamping it in an update callback cannot stop a drag —
#  Blender keeps feeding its own value in and the field sails past the last
#  frame and into negatives. It is therefore re-declared, with the live bounds,
#  whenever those bounds change. That also gives it a real slider.
# ─────────────────────────────────────────────────────────────────────────────

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty,
)
from bpy.types import PropertyGroup

from . import session


# ── the scrub control ───────────────────────────────────────────────────────

def _scrub_changed(self, context):
    """*self* is the WindowManager: this property is declared on the type."""
    if session.is_syncing():
        return              # our own write echoing back, not a user drag
    seq = session.get_sequence()
    if seq and seq.count:
        session.show_index(seq.index_of(self.bbav_frame))


def refresh_scrub():
    """Re-declare the scrub property with the current frame bounds.

    Called whenever the bounds move: a new sequence, or a change to the in/out
    range. Blender then enforces the limits itself, during dragging and typing
    alike, which an update callback cannot do.
    """
    st, seq = session.settings(), session.get_sequence()
    if st and seq and seq.count:
        lo, hi = session.active_range(st, seq)
        low, high = seq.frames[lo], seq.frames[hi]
    else:
        low, high = 0, 0
    high = max(low, high)

    bpy.types.WindowManager.bbav_frame = IntProperty(
        name="Frame",
        description="Frame being shown. Drag to scrub the sequence",
        default=low, min=low, max=high, soft_min=low, soft_max=high,
        update=_scrub_changed,
    )

    # Re-declaring resets the stored value, so put the playhead back.
    if st and seq and seq.count:
        index = max(0, min(st.frame_index, seq.count - 1))
        session.set_scrub(seq.frames[index])


# ── callbacks ───────────────────────────────────────────────────────────────

def _frame_index_changed(self, context):
    session.show_index(self.frame_index)


def _range_changed(self, context):
    """Tightening the range around the playhead should pull the playhead in,
    and the scrub control has to learn the new limits."""
    session.show_index(self.frame_index)
    refresh_scrub()


def _playing_changed(self, context):
    if self.playing:
        seq = session.get_sequence()
        # Restarting from the out point should roll back to the in point.
        if seq and seq.count:
            lo, hi = session.active_range(self, seq)
            if self.loop_mode == 'ONCE' and self.frame_index >= hi:
                session.show_index(lo)
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
    # The single source of truth. The frame number shown in the UI is derived
    # from it; see refresh_scrub above.
    frame_index: IntProperty(
        name="Index",
        description="Position within the sequence. Holes on disk are skipped",
        default=0, min=0,
        update=_frame_index_changed,
        options={'HIDDEN'},
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
    refresh_scrub()


def unregister():
    for owner, name in ((bpy.types.WindowManager, "bb_animviewer"),
                        (bpy.types.WindowManager, "bbav_frame")):
        if hasattr(owner, name):
            try:
                delattr(owner, name)
            except Exception:
                pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
