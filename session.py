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

# Last scene frame we reacted to, so the timeline can scrub the flipbook.
_last_scene_frame = None

# Set while we are pushing our own value into the scrub control, so its update
# callback can tell a user drag from an echo of our own write.
_syncing = False

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


def session_image():
    """The image datablock this session drives, if it still exists."""
    st = settings()
    if st is None or not st.image_name:
        return None
    return bpy.data.images.get(st.image_name)


def iter_viewer_areas():
    """Every Image Editor currently showing the session image.

    Membership is by displayed datablock, not by window: that way the popup
    window this addon opens and a render window the user adopted are both
    first-class hosts, and the controls follow the image rather than the frame
    it happens to be sitting in.
    """
    wm = getattr(bpy.context, "window_manager", None)
    image = session_image()
    if not wm or image is None:
        return
    for win in wm.windows:
        screen = win.screen
        if not screen:
            continue
        for area in screen.areas:
            if area.type != 'IMAGE_EDITOR':
                continue
            if area.spaces.active.image == image:
                yield win, area


def iter_popup_areas():
    """Only the windows this addon opened for itself."""
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
    """True when *space* is an image editor hosting the session."""
    image = session_image()
    if image is None or space is None or space.type != 'IMAGE_EDITOR':
        return False
    return space.image == image


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


def is_syncing():
    return _syncing


def set_scrub(number):
    """Push *number* into the scrub control without re-entering its callback.

    The ID-property write used for PropertyGroup members does not work here: a
    property declared straight onto a type does not read back through
    wm["name"] — verified, the two hold different values — so this has to go
    through RNA behind a re-entrancy flag.
    """
    global _syncing
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None or not hasattr(wm, "bbav_frame"):
        return
    if wm.bbav_frame == number:
        return
    _syncing = True
    try:
        wm.bbav_frame = number
    finally:
        _syncing = False


def show_index(index):
    """Move the playhead to *index* and display it.

    The single way the current frame changes. Writes go through the
    ID-property dict so the update callbacks do not re-enter, and the scrub
    control is kept in step with the real frame number.
    """
    st, seq = settings(), get_sequence()
    if not (st and seq) or not seq.count:
        return
    lo, hi = active_range(st, seq)
    index = max(lo, min(index, hi))
    st["frame_index"] = index
    set_scrub(seq.frames[index])
    apply_frame()


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

def scene_fps(scene=None):
    """The scene's render frame rate, honouring the NTSC-style fps_base."""
    scene = scene or bpy.context.scene
    render = scene.render
    return max(0.1, render.fps / max(1e-6, render.fps_base))


def effective_fps(st):
    """The rate playback actually runs at."""
    return scene_fps() if st.use_scene_fps else max(0.1, st.fps)


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


def _repin():
    """Re-pin frame_start so the displayed frame survives a scene frame change."""
    space = viewer_space()
    if space and space.image and space.image.source == 'SEQUENCE':
        if space.image_user.frame_start != bpy.context.scene.frame_current:
            apply_frame()


def _sync_scene_frame():
    """Let the scene timeline scrub the flipbook.

    Rendered frames carry the scene's frame numbers, so dragging the timeline to
    frame 7 should show frame 7. Mapping is by frame number, clamped into the
    sequence; a scene frame with no matching file simply holds at the nearest.

    Deliberately one-way. Driving scene.frame_current from playback would
    evaluate the depsgraph on every frame, which is the cost this viewer exists
    to avoid, so the timeline does not track the viewer during playback.
    """
    global _last_scene_frame
    scene_frame = bpy.context.scene.frame_current

    if _last_scene_frame is None:
        _last_scene_frame = scene_frame
        _repin()
        return
    if scene_frame == _last_scene_frame:
        _repin()
        return

    _last_scene_frame = scene_frame
    st, seq = settings(), get_sequence()
    if not (st and seq and seq.count) or not st.sync_scene_frame:
        _repin()
        return

    lo, hi = active_range(st, seq)
    number = max(seq.frames[lo], min(scene_frame, seq.frames[hi]))
    index = max(lo, min(seq.index_of(number), hi))
    if index != st.frame_index:
        show_index(index)
    else:
        _repin()


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
        _sync_scene_frame()
        return 0.25             # idle heartbeat, cheap

    period = 1.0 / effective_fps(st)
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


def _release_image(space=None):
    """Drop the previous viewer image so repeated opens do not pile up datablocks.

    Looking the image up by name alone is not enough: if the old one is still
    referenced elsewhere the new load gets uniquified to BB_AnimViewer.001 and
    the name lookup would keep finding the wrong one forever. The name check is
    kept as a guard so an image the user loaded into the window by hand is never
    removed from under them.
    """
    candidates = []
    for image in (space.image if space is not None else None,
                  session_image(),
                  bpy.data.images.get(IMAGE_NAME)):
        # Usually the same datablock twice; removing it once frees the other
        # reference, so de-duplicate before touching any of them.
        if image is not None and not any(image == seen for seen in candidates):
            candidates.append(image)

    for image in candidates:
        try:
            if image.name.startswith(IMAGE_NAME) and image.users <= 1:
                bpy.data.images.remove(image)
        except ReferenceError:
            pass


def _new_popup_window(context):
    """Open the dedicated viewer window. Returns (space, error)."""
    window = context.window
    area = max(window.screen.areas, key=lambda a: a.width * a.height)
    before = set(context.window_manager.windows)
    with context.temp_override(window=window, area=area):
        bpy.ops.wm.window_new()
    new = [w for w in context.window_manager.windows if w not in before]
    if not new:
        return None, "Blender refused to open a new window"

    win = new[0]
    win.screen.name = SCREEN_PREFIX
    area = win.screen.areas[0]
    area.type = 'IMAGE_EDITOR'
    space = area.spaces.active
    space.display_channels = 'COLOR'
    return space, None


def _prepare_space(space):
    global _focus_tries
    space.mode = 'VIEW'
    # A flipbook with its controls hidden behind N is not a flipbook.
    space.show_region_ui = True
    _focus_tries = 0
    if not bpy.app.timers.is_registered(_focus_sidebar):
        bpy.app.timers.register(_focus_sidebar, first_interval=0.05)


def open_viewer(context, seq, index=0, space=None):
    """Show *seq* in the viewer.

    With *space* given, that Image Editor is adopted as the host — this is how
    the window Blender opens for a render becomes the flipbook in place. Without
    it, an existing host is reused, or the dedicated popup window is opened.

    Returns an error string, or None on success.
    """
    if not seq or not seq.count:
        return "No image sequence found"

    st = settings()
    set_sequence(seq)

    host = space if space is not None else viewer_space()
    if host is None:
        host, error = _new_popup_window(context)
        if error:
            return error
    _prepare_space(host)

    _release_image(host)
    image = bpy.data.images.load(seq.path_at(index), check_existing=False)
    image.name = IMAGE_NAME
    image.source = 'FILE' if seq.is_still else 'SEQUENCE'
    host.image = image
    st.image_name = image.name          # may have been uniquified on load

    st.filepath = seq.path_at(index)
    st.seq_label = seq.label()
    st.frame_count = seq.count
    st.frame_first = seq.first
    st.frame_last = seq.last
    # In/out points from a previous sequence mean nothing for this one. Written
    # through the ID-property dict so the range callbacks do not fire and drag
    # the playhead around before the new frame is even set.
    st["use_range"] = False
    st["range_start"] = 0
    st["range_end"] = seq.count - 1
    st.ping_dir = 1
    st.playing = False
    st["frame_index"] = max(0, min(index, seq.count - 1))
    from . import properties          # lazy: properties imports this module
    properties.refresh_scrub()

    global _last_scene_frame
    _last_scene_frame = bpy.context.scene.frame_current

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
    """End the session: close our own window, and hand any adopted one back.

    Only windows this addon opened are closed. A render window the user adopted
    is left standing — removing the image datablock is enough to release it, and
    closing someone else's window out from under them would be rude.
    """
    st = settings()
    if st:
        st.playing = False
    stop_clock()

    for win, _area in list(iter_popup_areas()):
        try:
            with context.temp_override(window=win):
                bpy.ops.wm.window_close()
        except RuntimeError:
            pass

    _release_image()
    set_sequence(None)
    if st:
        st.image_name = ""
