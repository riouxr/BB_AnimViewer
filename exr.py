# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – OpenEXR header inspection
#
#  Blender does not expose the layer/pass inventory of a multilayer EXR to
#  Python (Image.layers does not exist; ImageUser.multilayer_* are read-only).
#  To *show* the user what is inside a frame we parse the EXR header
#  ourselves — header only, no pixel data, so it stays cheap even on 4K plates.
# ─────────────────────────────────────────────────────────────────────────────

import os
import struct

MAGIC = b"\x76\x2f\x31\x01"

# A channel entry is: name NUL, then a fixed 16-byte record
# (pixelType int32, pLinear uchar, 3x reserved uchar, xSampling int32, ySampling int32).
_CHANNEL_RECORD = 16

# Headers are small; this cap keeps a corrupt/huge file from being slurped whole.
_MAX_HEADER = 1 << 20

# Trailing token of a channel name that denotes the component rather than the pass.
_COMPONENTS = ("R", "G", "B", "A", "X", "Y", "Z", "U", "V", "W")

# Bounded FIFO — during playback we probe one header per frame and must not grow forever.
_CACHE_MAX = 64
_cache = {}


def _read_attributes(data):
    """Yield (name, type, payload) for the single-part header at the head of *data*."""
    i = 8  # magic + version
    while i < len(data):
        end = data.find(b"\x00", i)
        if end < 0:
            return
        name = data[i:end].decode("utf-8", "replace")
        i = end + 1
        if not name:                       # empty name terminates the header
            return
        end = data.find(b"\x00", i)
        if end < 0:
            return
        typ = data[i:end].decode("utf-8", "replace")
        i = end + 1
        if i + 4 > len(data):
            return
        (size,) = struct.unpack("<i", data[i:i + 4])
        i += 4
        if size < 0 or i + size > len(data):
            return
        yield name, typ, data[i:i + size]
        i += size


def _split_channel(name):
    """'ViewLayer.Combined.R' -> ('ViewLayer', 'Combined', 'R');  'R' -> ('', '', 'R')."""
    parts = name.split(".")
    if len(parts) == 1:
        return "", "", parts[0]
    comp = parts[-1]
    if comp not in _COMPONENTS:
        # e.g. a bare "Depth" style channel — treat the whole thing as the pass.
        return (parts[0], ".".join(parts[1:]), "") if len(parts) > 1 else ("", name, "")
    rest = parts[:-1]
    if len(rest) == 1:
        return "", rest[0], comp
    return rest[0], ".".join(rest[1:]), comp


def data_window_size(filepath):
    """(width, height) from the EXR header's dataWindow, or None.

    Header-only, like read_channels — used to size the viewer to the image
    before Blender has decoded any pixels, avoiding a resize once it does.
    """
    try:
        with open(filepath, "rb") as fh:
            if fh.read(4) != MAGIC:
                return None
            fh.seek(0)
            data = fh.read(_MAX_HEADER)
    except OSError:
        return None

    for name, typ, payload in _read_attributes(data):
        if name == "dataWindow" and len(payload) >= 16:
            xmin, ymin, xmax, ymax = struct.unpack("<iiii", payload[:16])
            w, h = xmax - xmin + 1, ymax - ymin + 1
            return (w, h) if w > 0 and h > 0 else None
    return None


def read_channels(filepath):
    """Return the ordered channel-name list of an EXR, or None if not a readable EXR."""
    try:
        with open(filepath, "rb") as fh:
            if fh.read(4) != MAGIC:
                return None
            fh.seek(0)
            data = fh.read(_MAX_HEADER)
    except OSError:
        return None

    for name, typ, payload in _read_attributes(data):
        if name != "channels":
            continue
        names = []
        j = 0
        while j < len(payload) and payload[j] != 0:
            end = payload.find(b"\x00", j)
            if end < 0:
                break
            names.append(payload[j:end].decode("utf-8", "replace"))
            j = end + 1 + _CHANNEL_RECORD
        return names
    return None


def inspect(filepath):
    """Describe an EXR as {'layers': {layer: {pass: [components]}}, 'channels': n}.

    Results are cached per (path, mtime) — the panel redraws constantly and we do
    not want a file probe on every draw call.
    """
    try:
        key = (filepath, os.path.getmtime(filepath))
    except OSError:
        return None
    hit = _cache.get(key)
    if hit is not None:
        return hit

    names = read_channels(filepath)
    if names is None:
        return None

    layers = {}
    for name in names:
        layer, passname, comp = _split_channel(name)
        passes = layers.setdefault(layer, {})
        passes.setdefault(passname, []).append(comp)

    info = {"layers": layers, "channels": len(names)}
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = info
    return info


def is_multilayer(filepath):
    """True when the EXR carries more than a single plain RGBA pass."""
    info = inspect(filepath)
    if not info:
        return False
    total = sum(len(p) for p in info["layers"].values())
    return total > 1 or any(layer for layer in info["layers"])


def summary(filepath):
    """Short 'Layer > pass, pass, ...' lines for display in the sidebar."""
    info = inspect(filepath)
    if not info:
        return []
    out = []
    for layer, passes in info["layers"].items():
        out.append((layer or "(root)", list(passes.keys())))
    return out
