# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – viewer window, frame addressing and playback clock
#
#  Frame addressing note (verified against Blender 4.5 and 5.1):
#      framenr = clamp(scene_frame - frame_start + 1, 1, frame_duration) + frame_offset
#  and for a SEQUENCE image the file number on disk *is* framenr. The offset is
#  applied after the clamp, which is what makes 1001-based sequences work.
#  By pinning frame_start to the current scene frame the clamped term is always
#  1, so "frame_offset = number - 1" displays exactly the file we want without
#  ever touching scene.frame_current.
#
#  ImageUser.frame_current is only recomputed when the editor actually draws, so
#  it is never read back — this module is the single source of truth.
# ─────────────────────────────────────────────────────────────────────────────

import time

import bpy

from . import sequence as seqmod

SCREEN_PREFIX = "BB_AnimViewer"
IMAGE_NAME = "BB_AnimViewer"

# The detected Sequence for the open session. Module state rather than RNA
# because a Sequence holds a frame list that has no good PropertyGroup shape.
_sequence = None

_last_tick = 0.0
_timer_live = False

# Reload guard. bpy.app.timers keeps a reference to the *old* module's _tick
# across a script reload, and is_registered() cannot match it against the new
# function object, so it would keep firing and fight the fresh instance for the
# frame. The generation counter lives in driver_namespace, which survives the
# reload; a tick whose generation is stale retires itself on its next fire.
_GEN_KEY = "bb_animviewer_generation"
_my_gen = 0


def claim_generation():
    """Take ownership of the playback clock, retiring any older instance."""
    global _my_gen
    _my_gen = bpy.app.driver_namespace.get(_GEN_KEY, 0) + 1
    bpy.app.driver_namespace[_GEN_KEY] = _my_gen


def _is_current():
    return _my_gen == bpy.app.driver_namespace.get(_GEN_KEY, _my_gen)

# Never fast-forward more than this after a stall (a long redraw, a file dialog).
_MAX_CATCHUP = 8


# ── access ──────────────────────────────────────────────────────────────────

def settings():
    wm = getattr(bpy.context, "window_manager", None)
    return getattr(wm, "bb_animviewer", None) if wm else None


def get_sequence():
    """The live Sequence, rebuilt from the stored path if module state was lost."""
    global _sequence
    if _sequence is not None:
        return _sequence
    st = settings()
    if st and st.filepath:
        _sequence = seqmod.from_file(st.filepath)
    return _sequence


def set_sequence(seq):
    global _sequence
    _sequence = seq


def iter_viewer_areas():
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return
    for win in wm.windows:
        screen = win.screen
        if not screen or not screen.name.startswith(SCREEN_PREFIX):
            continue
        for area in screen.areas:
            if area.type == 'IMAGE_EDITOR':
                yield win, area


def viewer_space():
    for _win, area in iter_viewer_areas():
        return area.spaces.active
    return None


def viewer_open():
    return viewer_space() is not None


def is_viewer_space(space):
    """True when *space* is the image editor belonging to an open viewer window."""
    for _win, area in iter_viewer_areas():
        if area.spaces.active == space:
            return True
    return False


def redraw():
    for _win, area in iter_viewer_areas():
        for region in area.regions:
            region.tag_redraw()


# ── frame addressing ────────────────────────────────────────────────────────

def apply_frame(index=None):
    """Point the viewer's image at frame *index* of the sequence."""
    st, seq, space = settings(), get_sequence(), viewer_space()
    if not (st and seq and space) or not seq.count:
        return
    image = space.image
    if image is None:
        return

    if index is None:
        index = st.frame_index
    index = max(0, min(index, seq.count - 1))

    iu = space.image_user
    if seq.is_still:
        image.source = 'FILE'
        redraw()
        return

    image.source = 'SEQUENCE'
    iu.frame_duration = max(1, seq.count)
    iu.use_cyclic = False
    iu.use_auto_refresh = True
    iu.frame_start = bpy.context.scene.frame_current
    iu.frame_offset = seq.frames[index] - 1
    redraw()


def current_number():
    seq, st = get_sequence(), settings()
    if not (seq and st) or not seq.count:
        return 0
    return seq.frames[max(0, min(st.frame_index, seq.count - 1))]


def current_path():
    seq, st = get_sequence(), settings()
    if not (seq and st) or not seq.count:
        return ""
    return seq.path_at(st.frame_index)


def active_range(st, seq):
    """In/out point as sequence indices, honouring the range toggle."""
    last = seq.count - 1
    if not st.use_range:
        return 0, last
    lo = max(0, min(st.range_start, last))
    hi = max(0, min(st.range_end, last))
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


# ── playback clock ──────────────────────────────────────────────────────────

def _advance(st, seq, steps):
    lo, hi = active_range(st, seq)
    index = max(lo, min(st.frame_index, hi))

    for _ in range(steps):
        if st.loop_mode == 'PINGPONG':
            index += 1 if st.ping_dir >= 0 else -1
            if index > hi:
                index = max(lo, hi - 1)
                st.ping_dir = -1
            elif index < lo:
                index = min(hi, lo + 1)
                st.ping_dir = 1
        else:
            index += 1
            if index > hi:
                if st.loop_mode == 'LOOP':
                    index = lo
                else:
                    index = hi
                    st.playing = False
                    break

    st.frame_index = index      # update callback applies the frame


def _guard_scene_frame():
    """Re-pin if the user scrubbed the scene timeline out from under us."""
    space = viewer_space()
    if space and space.image and space.image.source == 'SEQUENCE':
        if space.image_user.frame_start != bpy.context.scene.frame_current:
            apply_frame()


def _tick():
    global _last_tick, _timer_live
    if not _is_current():
        return None             # a newer instance of the addon has taken over
    if not viewer_open():
        _timer_live = False
        return None

    st, seq = settings(), get_sequence()
    if st is None or seq is None or not seq.count:
        _timer_live = False
        return None

    if not st.playing:
        _guard_scene_frame()
        return 0.25             # idle heartbeat, cheap

    period = 1.0 / max(0.1, st.fps)
    now = time.perf_counter()
    elapsed = now - _last_tick
    _last_tick = now

    if st.drop_frames:
        steps = max(1, min(_MAX_CATCHUP, int(round(elapsed / period))))
    else:
        steps = 1

    _advance(st, seq, steps)
    return period


def start_clock():
    global _last_tick, _timer_live
    _last_tick = time.perf_counter()
    if not _timer_live:
        _timer_live = True
        bpy.app.timers.register(_tick, first_interval=0.0)


def stop_clock():
    global _timer_live
    _timer_live = False
    for func in (_tick, _focus_sidebar):
        if bpy.app.timers.is_registered(func):
            try:
                bpy.app.timers.unregister(func)
            except ValueError:
                pass


# ── window management ───────────────────────────────────────────────────────

_focus_tries = 0


def _focus_sidebar():
    """Bring the Viewer tab to the front of the sidebar.

    Deferred and retried: right after the area is switched to IMAGE_EDITOR its
    sidebar region has not been built yet, so an immediate assignment is
    silently dropped and the user lands on whatever tab was showing before.
    """
    global _focus_tries
    _focus_tries += 1
    for _win, area in iter_viewer_areas():
        for region in area.regions:
            if region.type != 'UI':
                continue
            try:
                region.active_panel_category = "Viewer"
            except (AttributeError, TypeError):
                return None          # build does not allow picking the tab
            if region.active_panel_category == "Viewer":
                redraw()
                return None
    return 0.1 if _focus_tries < 20 else None


def _release_image():
    existing = bpy.data.images.get(IMAGE_NAME)
    if existing is not None and existing.users <= 1:
        bpy.data.images.remove(existing)


def open_viewer(context, seq, index=0):
    """Open (or reuse) the popup viewer window on *seq*.

    Returns an error string, or None on success.
    """
    if not seq or not seq.count:
        return "No image sequence found"

    st = settings()
    set_sequence(seq)

    space = viewer_space()
    if space is None:
        window = context.window
        area = max(window.screen.areas, key=lambda a: a.width * a.height)
        before = set(context.window_manager.windows)
        with context.temp_override(window=window, area=area):
            bpy.ops.wm.window_new()
        new = [w for w in context.window_manager.windows if w not in before]
        if not new:
            return "Blender refused to open a new window"
        win = new[0]
        win.screen.name = SCREEN_PREFIX
        area = win.screen.areas[0]
        area.type = 'IMAGE_EDITOR'
        space = area.spaces.active
        space.mode = 'VIEW'
        space.display_channels = 'COLOR'
        # A flipbook with its controls hidden behind N is not a flipbook.
        space.show_region_ui = True
        global _focus_tries
        _focus_tries = 0
        bpy.app.timers.register(_focus_sidebar, first_interval=0.05)

    _release_image()
    image = bpy.data.images.load(seq.path_at(index), check_existing=False)
    image.name = IMAGE_NAME
    image.source = 'FILE' if seq.is_still else 'SEQUENCE'
    space.image = image

    st.filepath = seq.path_at(index)
    st.seq_label = seq.label()
    st.frame_count = seq.count
    st.frame_first = seq.first
    st.frame_last = seq.last
    st.range_start = 0
    st.range_end = seq.count - 1
    st.ping_dir = 1
    st.playing = False
    index = max(0, min(index, seq.count - 1))
    st["frame_index"] = index
    st["frame_number"] = seq.frames[index]

    apply_frame()
    fit_view()
    start_clock()
    return None


def fit_view():
    for win, area in iter_viewer_areas():
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            continue
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                bpy.ops.image.view_all(fit_view=True)
        except RuntimeError:
            pass
        return


def close_viewer(context):
    st = settings()
    if st:
        st.playing = False
    stop_clock()
    for win, _area in list(iter_viewer_areas()):
        try:
            with context.temp_override(window=win):
                bpy.ops.wm.window_close()
        except RuntimeError:
            pass
    _release_image()
    set_sequence(None)
