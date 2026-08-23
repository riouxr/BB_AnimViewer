# ─────────────────────────────────────────────────────────────────────────────
#  BB AnimViewer – an fcheck-style flipbook for image sequences
#  Location : Render ▶ BB AnimViewer
# ─────────────────────────────────────────────────────────────────────────────

bl_info = {
    "name":        "BB AnimViewer",
    "author":      "Blender Bob + Claude.ai",
    "version":     (1, 2, 1),
    "blender":     (4, 2, 0),
    "location":    "Render › BB AnimViewer",
    "description": "Flipbook viewer for image sequences with transport controls "
                   "and EXR layer/pass selection",
    "category":    "Render",
}

if "bpy" in locals():
    import importlib
    for mod in (exr, sequence, session, properties, operators, keymaps, ui):
        importlib.reload(mod)
    print("Add-on Reloaded: BB AnimViewer")
else:
    import bpy
    from . import (
        exr,
        sequence,
        session,
        properties,
        operators,
        keymaps,
        ui,
    )


#### ------------------------------ REGISTRATION ------------------------------ ####

modules = (
    properties,
    operators,
    keymaps,
    ui,
)


def register():
    session.claim_generation()
    for mod in modules:
        mod.register()


def unregister():
    # Leaving a stray timer or an orphan viewer window behind survives an addon
    # disable and confuses the next enable, so tear the session down first.
    session.stop_clock()
    session.set_sequence(None)

    for mod in reversed(modules):
        try:
            mod.unregister()
        except Exception as ex:            # never strand a half-torn-down addon
            print("BB AnimViewer: %s.unregister() failed: %s" % (mod.__name__, ex))


if __name__ == "__main__":
    register()
