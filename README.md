# BB AnimViewer

An fcheck-style flipbook for Blender. Blender's own "Play Rendered Animation" throws
an image sequence at a bare window and gives you nothing to drive it with — no stop,
no frame stepping, no way to look at a different channel. This is that window, with
the controls attached.

**Location:** `Render ▶ BB AnimViewer`

---

## What it does

* **Transport** — play, pause, step a frame at a time, jump to either end, scrub by
  typing or dragging a real frame number.
* **Loop, ping-pong or play once**, at any frame rate, independent of the scene's.
* **In / out points** to review a sub-range.
* **Channels** — RGB, RGBA, Alpha, Z, and single R / G / B isolation.
* **EXR layers and passes** — every layer, pass and view inside a multilayer EXR,
  not just RGBAZ. The Sequence panel also lists what a frame actually contains,
  read straight from the EXR header.
* **Colour management** — view transform, look, exposure and gamma, right next to
  the image where you need them for float EXRs.
* **Holes are skipped.** The frame list is the files that are really on disk, so a
  half-finished render steps 1004 → 1007 instead of flashing missing frames.
* **Reload** re-scans the folder, so you can keep the viewer open while a render
  fills the directory in.

It never touches `scene.frame_current`, so it will not disturb your scene or trigger
depsgraph evaluation while you review.

---

## Keys

Active only inside the viewer window — your other Image Editors keep their normal
bindings.

| Key | Action |
| --- | --- |
| `Space` / `Return` | Play / pause |
| `→` / `←` or `.` / `,` | Next / previous frame |
| `↑` / `↓` | Forward / back 10 frames |
| `Home` / `End` | First / last frame |
| `Shift →` / `Shift ←` | Last / first frame |
| `R` `G` `B` | Isolate red, green, blue |
| `A` | Alpha |
| `Z` | Depth |
| `C` | Back to full colour |
| `I` / `O` | Set in / out point |
| `L` | Cycle loop mode |
| `F` | Fit image to window |
| `F5` | Reload from disk |

Pressing a channel key a second time returns to full colour.

---

## Install

Blender 4.2 or newer.

1. Download the repository as a ZIP.
2. `Edit ▶ Preferences ▶ Add-ons ▶ Install from Disk`, pick the ZIP.
3. Enable **BB AnimViewer**.

Then `Render ▶ BB AnimViewer ▶ Open Render Output` to review what you just rendered,
or `Open Sequence...` to point it at anything else.

---

## Known limitation

Switching multilayer EXR passes is done through Blender's own Layer / Pass / View
dropdowns, which the panel embeds. There is no hotkey to cycle passes because
`ImageUser.multilayer_layer`, `multilayer_pass` and `multilayer_view` are read-only
to Python — Blender drives them from C in the UI template and exposes no operator.
If that ever changes, pass cycling becomes a two-line addition.

---

## How the frame addressing works

Noted here because it is the non-obvious part, verified against Blender 4.5 and 5.1:

```
framenr = clamp(scene_frame - frame_start + 1, 1, frame_duration) + frame_offset
```

For a `SEQUENCE` image the file number on disk *is* `framenr`, and the offset is
applied *after* the clamp — which is what makes 1001-based sequences work at all.
Pinning `frame_start` to the current scene frame makes the clamped term always 1, so
`frame_offset = number - 1` displays exactly the wanted file without moving the
scene's frame.

`ImageUser.frame_current` is only recomputed when the editor actually draws, so it is
never read back; the addon tracks the current frame itself.

---

Blender Bob & Claude — GPL-3.0-or-later
