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

    __slots__ = ("directory", "stem", "ext", "padding", "frames", "mtime")

    def __init__(self, directory, stem, ext, padding, frames, mtime=0.0):
        self.directory = directory
        self.stem = stem
        self.ext = ext
        self.padding = padding
        self.frames = frames          # sorted list of real frame numbers
        self.mtime = mtime            # when this version was last written

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
    """Return every sequence in *directory*, most recently written first.

    Recency rather than frame count decides the order, because a folder holding
    several versions of the same shot should offer the one just rendered — not
    whichever has the most frames, and certainly not whichever sorts first
    alphabetically, which put v001 ahead of v003.

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
        seq = Sequence(directory, stem, ext, padding, frames)
        # One stat per sequence, on the highest-numbered frame: for a render
        # that is the last frame written, and walking every file in a big
        # directory to find the true maximum is not worth the I/O.
        try:
            seq.mtime = os.path.getmtime(seq.path_for(frames[-1]))
        except OSError:
            seq.mtime = 0.0
        out.append(seq)

    out.sort(key=lambda s: (-s.mtime, -s.count, s.name.lower()))
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


def render_output_target(scene):
    """(directory, name prefix) for the scene's render output.

    The prefix is the part Blender puts before the frame number, and it is what
    identifies *which* version was just rendered when several live side by side
    in one folder. Empty when the output path names only a directory.
    """
    import bpy
    path = bpy.path.abspath(scene.render.filepath)
    if not path:
        return "", ""
    # A trailing separator means Blender appends its own frame numbers there.
    if path.endswith(("/", "\\")) or os.path.isdir(path):
        return os.path.normpath(path), ""
    directory, base = os.path.split(path)
    # Blender substitutes the frame number for a run of "#", so the prefix is
    # whatever precedes it — "ColoTest.####.png" renders "ColoTest.0001.png".
    # With no "#" at all the number is appended to the whole basename instead,
    # extension included, so that case must not be trimmed.
    if "#" in base:
        base = base.split("#", 1)[0]
    return os.path.normpath(directory), base


def resolve_render_output(scene):
    """Best-guess directory for the scene's rendered frames."""
    return render_output_target(scene)[0]


def pick(sequences, prefix=""):
    """The sequence the user most likely means out of *sequences*.

    A prefix from the render output path wins, so re-rendering under a new name
    shows that name. Otherwise the most recently written one, since scan()
    already returns them newest first.
    """
    if not sequences:
        return None
    if prefix:
        matches = [s for s in sequences if s.stem == prefix or s.stem.startswith(prefix)]
        if matches:
            return matches[0]
    return sequences[0]
