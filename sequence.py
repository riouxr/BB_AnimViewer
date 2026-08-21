# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – image sequence detection
#
#  A sequence is a set of files sharing a stem and extension and differing only
#  in a trailing number: plate.1001.exr, plate.1002.exr, ...
#  We keep the *actual* frame numbers found on disk rather than assuming a
#  contiguous range, so playback steps over holes instead of showing missing
#  frames the way Blender's own sequence addressing would.
# ─────────────────────────────────────────────────────────────────────────────

import os
import re

# Non-greedy stem: for "Plate01.0001.png" a greedy stem would split as
# ("Plate01.000", "1", ".png"). Non-greedy backtracks off the extension anchor
# and lands on ("Plate01.", "0001", ".png").
SEQ_RE = re.compile(r"^(?P<stem>.*?)(?P<num>\d+)(?P<ext>\.[A-Za-z0-9]+)$")

IMAGE_EXTS = {
    ".png", ".jpg", ".jpeg", ".exr", ".dpx", ".cin", ".tif", ".tiff",
    ".tga", ".bmp", ".hdr", ".jp2", ".j2c", ".webp", ".sgi", ".rgb",
}

# Guard against a pathological directory stalling the UI thread.
MAX_FILES = 20000


class Sequence:
    """One detected image sequence."""

    __slots__ = ("directory", "stem", "ext", "padding", "frames")

    def __init__(self, directory, stem, ext, padding, frames):
        self.directory = directory
        self.stem = stem
        self.ext = ext
        self.padding = padding
        self.frames = frames          # sorted list of real frame numbers

    # ── identity ────────────────────────────────────────────────────────────
    @property
    def key(self):
        return (self.directory, self.stem, self.ext, self.padding)

    @property
    def name(self):
        if not self.padding:                      # a standalone still
            return "%s%s" % (self.stem, self.ext)
        return "%s%s%s" % (self.stem, "#" * self.padding, self.ext)

    @property
    def is_still(self):
        return not self.padding

    @property
    def count(self):
        return len(self.frames)

    @property
    def first(self):
        return self.frames[0] if self.frames else 0

    @property
    def last(self):
        return self.frames[-1] if self.frames else 0

    @property
    def is_contiguous(self):
        return bool(self.frames) and self.count == (self.last - self.first + 1)

    @property
    def missing(self):
        """How many frame numbers inside the range have no file on disk."""
        if not self.frames:
            return 0
        return (self.last - self.first + 1) - self.count

    # ── paths ───────────────────────────────────────────────────────────────
    def path_for(self, number):
        if not self.padding:                      # a still has no number to substitute
            return os.path.join(self.directory, "%s%s" % (self.stem, self.ext))
        return os.path.join(self.directory,
                            "%s%0*d%s" % (self.stem, self.padding, number, self.ext))

    def path_at(self, index):
        if not self.frames:
            return ""
        index = max(0, min(index, self.count - 1))
        return self.path_for(self.frames[index])

    def index_of(self, number):
        """Index of *number*, or the nearest frame at or before it."""
        best = 0
        for i, n in enumerate(self.frames):
            if n == number:
                return i
            if n < number:
                best = i
        return best

    def label(self):
        if not self.frames:
            return "%s  (empty)" % self.name
        if self.is_still:
            return self.name
        gap = "  (%d missing)" % self.missing if self.missing else ""
        return "%s  [%d-%d]  %d frames%s" % (
            self.name, self.first, self.last, self.count, gap)


def scan(directory):
    """Return every sequence in *directory*, richest first.

    Single stills are returned too, as one-frame sequences, so the viewer can
    open a lone image without a special case.
    """
    try:
        entries = os.listdir(directory)
    except OSError:
        return []

    groups = {}
    for i, filename in enumerate(entries):
        if i >= MAX_FILES:
            break
        match = SEQ_RE.match(filename)
        if match:
            stem, num, ext = match.group("stem"), match.group("num"), match.group("ext")
            if ext.lower() not in IMAGE_EXTS:
                continue
            if not os.path.isfile(os.path.join(directory, filename)):
                continue
            groups.setdefault((stem, ext, len(num)), []).append(int(num))
            continue

        # No trailing number — a standalone still such as "background.png".
        stem, ext = os.path.splitext(filename)
        if ext.lower() not in IMAGE_EXTS:
            continue
        if not os.path.isfile(os.path.join(directory, filename)):
            continue
        groups.setdefault((stem, ext, 0), []).append(0)

    out = []
    for (stem, ext, padding), frames in groups.items():
        frames.sort()
        out.append(Sequence(directory, stem, ext, padding, frames))

    out.sort(key=lambda s: (-s.count, s.name.lower()))
    return out


def from_file(filepath):
    """Detect the sequence that *filepath* belongs to."""
    directory, filename = os.path.split(filepath)
    match = SEQ_RE.match(filename)
    if not match:
        stem, ext = os.path.splitext(filename)
        if not os.path.isfile(filepath):
            return None
        return Sequence(directory, stem, ext, 0, [0])

    stem, num, ext = match.group("stem"), match.group("num"), match.group("ext")
    padding = len(num)
    for seq in scan(directory):
        if seq.key == (directory, stem, ext, padding):
            return seq
    return None


def resolve_render_output(scene):
    """Best-guess directory for the scene's rendered frames."""
    import bpy
    path = bpy.path.abspath(scene.render.filepath)
    if not path:
        return ""
    # A trailing separator means Blender appends its own frame numbers there.
    if path.endswith(("/", "\\")) or os.path.isdir(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.dirname(path))
