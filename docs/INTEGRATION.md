# Calling Pixel Forge from another app (protocol 1)

Pixel Forge is developed here, on its own. Other apps (Grass Block) don't
import its code. They **start `Pixel Forge.exe` with options, wait for it to
close, and read the result**. This file is the whole contract. Anything not
described here can change freely. A change that would break a caller bumps
`protocol`; a new ability is added to `modes` instead (see `--describe`), and
callers check for it before offering it.

## Edit an existing texture

```
"Pixel Forge.exe" --edit <texture.png> [--name "Flesh Axe"] [--caller "Grass Block"] [--result <result.json>]
```

- The texture opens **exactly as it is** (no pixel-art generation) as one layer
  named *Texture*. The Pen tool is selected.
- The panel on the right offers **Remove BG: Plain / AI** for the selected layer, with Ctrl+Z to undo.
  Plain takes away the colour around the edges; AI keeps the subject a neural network finds.
- The user paints and adds layers, then presses **Save & Return** (or Ctrl+S) or **Cancel**.
  Closing the window counts as Cancel, and asks first if something was painted.
- **Save & Return overwrites `<texture.png>`** with the flattened result: every visible
  layer, same size, RGBA PNG. Cancel leaves the file byte-for-byte untouched.
- `--name` is shown in the Minecraft preview tab. `--caller` is shown in the top bar
  ("Editing for Grass Block: flesh_axe.png").
- Accepted textures are **square PNGs from 8x8 to 256x256**. Anything else is an error
  (exit 1) and the window never opens. Animated strips (e.g. 16x64) are not supported
  in protocol 1.

**Recommended use:** copy the texture to a temp file, edit the copy, and on
`saved` write the copy back with your own save path. That way your
validation, change journal and undo still apply, and a crash can't
half-write the real file.

## Make a texture from a picture (mode `convert`)

```
"Pixel Forge.exe" --edit <texture.png> --source <picture> [--transparent] [--name "Flesh Axe"] [--caller "Grass Block"] [--result <result.json>]
```

- The picture goes through Pixel Forge's **pixel-art converter**, at the texture's size.
  - The grid is fixed to that size (shown as "Grid Resolution: 16 x 16 (the texture's size)").
  - Every other converter setting is there: palette limit, sprite clean-up, outline and detail
    lines, **Remove BG (Plain or AI)**, Transparent BG, zoom to fit, scale and position, and Match
    Original.
- The user sets the converter, paints and adds layers, then presses **Save & Return** or **Cancel**,
  as when editing. Cancel asks first if something was painted or a setting changed.
- **Save & Return overwrites `<texture.png>`** with the art: every visible layer, at the texture's
  size, RGBA PNG.
- `<texture.png>` must be acceptable to `--edit` (a square PNG, 8x8 to 256x256). Only its size is
  used: a blank one is fine.
- `<picture>` is anything Pillow opens (PNG, JPEG, GIF, BMP, WebP…), of any size. For an animation,
  its first frame is used. An unreadable picture is an error (exit 1), and the window never opens.
- `--transparent` starts with **Transparent BG** ticked, so the removed background is see-through
  rather than flattened to one colour. Pass it for textures that need see-through pixels, such as
  item icons.
- `--source` without `--edit` is a bad-arguments error (exit 1).
- Results and exit codes are as for editing.
- Check that `"convert"` is in `modes` before offering it.

## Ask what this Pixel Forge supports

```
"Pixel Forge.exe" --describe [--result <result.json>]
```

The command exits 0 at once and writes the description to the result file:

```json
{"protocol": 1, "app": "Pixel Forge", "modes": ["edit", "convert"], "formats": ["png"],
 "texture": {"square": true, "min": 8, "max": 256},
 "exit_codes": {"saved": 0, "cancelled": 10, "error": 1}}
```

Callers should check `protocol == 1`, and that `"edit"` is in `modes`, before
offering the feature. Before offering a picture to convert, they should also check
for `"convert"` (added 2026-09-27; older Pixel Forges only list `"edit"`).

## Results

| Exit code | `status` in result.json | Meaning |
|---|---|---|
| 0  | `saved`     | The texture file was overwritten. Also has `path`, `width`, `height`. |
| 10 | `cancelled` | The user cancelled. The file is unchanged. |
| 1  | `error`     | Bad arguments, an unusable texture, Pixel Forge not set up, or a crash. Has a readable `message`. |

- Every result has `"protocol": 1`.
- The result file is written atomically (a temp file, then a rename) just before the process exits.
- A missing result file with a non-zero exit code means the process was killed.
- The exit code alone is enough; the result file is optional but recommended (it has the error message).

## Waiting

`Pixel Forge.exe` is a small launcher. When **any argument starts with `--`**, it:

1. passes every argument through;
2. waits for the app to close;
3. returns the app's exit code.

The edit session lasts as long as the user keeps editing, so callers must
wait asynchronously and never time out. The launcher also finds the app
folder when it's been moved elsewhere (e.g. the Desktop).

If Pixel Forge's Python environment isn't installed yet, the launcher
returns exit code 1 with a message: *"open Pixel Forge once by itself"*. It
doesn't run the one-time setup for a calling app.

## Testing from the calling app

Two environment variables, meant for automated tests only:

- `PIXEL_FORGE_HIDDEN=1` hides the window and suppresses message boxes.
- `PIXEL_FORGE_TEST_ACTION` makes the session act by itself:
  - `save` saves the texture unchanged; when converting, the art as it first appears (default
    settings, plus `--transparent`);
  - `paint-save` paints pixel (0,0) magenta `#FF00FF`, then saves;
  - `remove-bg-save` / `remove-bg-ai-save` press Remove BG Plain / AI on the texture, then save
    (when editing; when converting they just save);
  - `cancel` cancels.

Example: `PIXEL_FORGE_HIDDEN=1 PIXEL_FORGE_TEST_ACTION=paint-save "Pixel Forge.exe" --edit t.png --result r.json`
must exit 0, and `t.png` gets a magenta top-left pixel.

## Where this lives in Pixel Forge

- `edit_session.py`: argument parsing, the session mode (`open_texture` for editing, `open_source`
  for converting), result files and exit codes.
- `pixel_forge.py` `main()`: wires it up. `_fix_grid` shows the fixed grid while converting.
- `launcher.cs`: passes arguments through, waits, forwards exit codes. Rebuild it with `build-launcher.bat`.
