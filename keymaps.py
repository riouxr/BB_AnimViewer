# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – fcheck-style keyboard control
#
#  Bound in the Image keymap. Every operator here polls for viewer focus, so the
#  bindings are inert in any other Image Editor and Blender's own behaviour for
#  these keys is left alone outside the viewer window.
# ─────────────────────────────────────────────────────────────────────────────

import bpy

_items = []

# (operator, key, modifiers, {property: value})
_BINDINGS = (
    ("bb_animviewer.play",  'SPACE',       {}, {"mode": 'TOGGLE'}),
    ("bb_animviewer.play",  'RET',         {}, {"mode": 'TOGGLE'}),

    ("bb_animviewer.step",  'RIGHT_ARROW', {}, {"delta": 1}),
    ("bb_animviewer.step",  'LEFT_ARROW',  {}, {"delta": -1}),
    ("bb_animviewer.step",  'PERIOD',      {}, {"delta": 1}),
    ("bb_animviewer.step",  'COMMA',       {}, {"delta": -1}),
    ("bb_animviewer.step",  'UP_ARROW',    {}, {"delta": 10}),
    ("bb_animviewer.step",  'DOWN_ARROW',  {}, {"delta": -10}),

    ("bb_animviewer.jump",  'HOME',        {}, {"to": 'START'}),
    ("bb_animviewer.jump",  'END',         {}, {"to": 'END'}),
    ("bb_animviewer.jump",  'LEFT_ARROW',  {"shift": True}, {"to": 'START'}),
    ("bb_animviewer.jump",  'RIGHT_ARROW', {"shift": True}, {"to": 'END'}),

    # fcheck channel keys — pressing the same key again returns to full colour.
    ("bb_animviewer.channel", 'R', {}, {"channel": 'RED'}),
    ("bb_animviewer.channel", 'G', {}, {"channel": 'GREEN'}),
    ("bb_animviewer.channel", 'B', {}, {"channel": 'BLUE'}),
    ("bb_animviewer.channel", 'A', {}, {"channel": 'ALPHA'}),
    ("bb_animviewer.channel", 'Z', {}, {"channel": 'Z_BUFFER'}),
    ("bb_animviewer.channel", 'C', {}, {"channel": 'COLOR'}),

    ("bb_animviewer.set_range", 'I', {}, {"edge": 'IN'}),
    ("bb_animviewer.set_range", 'O', {}, {"edge": 'OUT'}),

    ("bb_animviewer.cycle_loop", 'L', {}, {}),

    ("bb_animviewer.fit_view", 'F', {}, {}),
    ("bb_animviewer.reload",   'F5', {}, {}),
)


def register():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:                       # background mode has no addon keyconfig
        return
    km = kc.keymaps.new(name="Image", space_type='IMAGE_EDITOR')

    for idname, key, mods, props in _BINDINGS:
        kmi = km.keymap_items.new(idname, key, 'PRESS', **mods)
        for name, value in props.items():
            setattr(kmi.properties, name, value)
        _items.append((km, kmi))


def unregister():
    for km, kmi in _items:
        try:
            km.keymap_items.remove(kmi)
        except (RuntimeError, ReferenceError):
            pass
    _items.clear()
