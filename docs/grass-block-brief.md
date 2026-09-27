# Brief for Grass Block: "Edit in Pixel Forge…"

**Goal:** Grass Block gets an **Edit in Pixel Forge…** action for textures. It
opens the current texture in Pixel Forge, waits, and brings the edited
texture back. Pixel Forge stays a separate project in
`The LAB\pixel-art-generator`, where all of its development happens. Grass Block
only calls it, using the contract in
`pixel-art-generator\docs\INTEGRATION.md` (protocol 1). **Do not copy or import Pixel Forge code.**

## 1. Setting: where Pixel Forge is

- Add `pixelForgePath` to the settings (`readSettings`/`writeSettings` in `main.js`).
- Auto-detect when it's unset: `path.join(__dirname, '..', 'pixel-art-generator', 'Pixel Forge.exe')`.
  Both projects live in `The LAB`.
- Detect once per app start with `"Pixel Forge.exe" --describe --result <tmp>.json` (exit 0,
  `protocol === 1`, `modes` includes `"edit"`). If that fails, or the file is missing,
  hide or disable the action and give it the tooltip "Pixel Forge not found. Set its location in Settings".
- Add a "Pixel Forge location…" picker next to the existing Blockbench one (`pick-blockbench-java` is the model to follow).

## 2. Main process: `ipcMain.handle('edit-texture-external', (e, workspace, textureId, name))`

1. Read the current PNG (the same way `write-texture`/`ws.texturePath` resolve it) and
   check that it's square and 8–256 px. Animated strips aren't supported in protocol 1:
   return a clear error instead of calling Pixel Forge.
2. Copy it to a temp file: `os.tmpdir()/grass-block-pf/<random>/<texture name>.png`. Keep the
   file name, because Pixel Forge shows it.
3. Spawn the exe with `child_process.spawn(exe, ['--edit', tmp, '--name', name, '--caller',
   'Grass Block', '--result', resultJson], { windowsHide: false })`. Pass the arguments as
   an array (no shell, no string concatenation), because paths have spaces.
4. Await `exit` with **no timeout**, because the user may edit for a long time. Allow only one
   session per texture: a second click focuses nothing and returns `busy`.
5. Handle the exit code:
   - **0 (saved):** read the temp PNG and pass it to the existing `ws.writeTexture(root, textureId, base64)`.
     Its validation and change-journal entry then apply as usual.
     Return `{ status: 'saved', relativePath, width, height }`.
   - **10 (cancelled):** return `{ status: 'cancelled' }` and write nothing.
   - **Anything else:** return `{ status: 'error', message }`, using `message` from the result JSON when present.
6. Always delete the temp folder afterwards.

## 3. Preload and renderer

- In `preload.js`, add `editTextureExternal(workspace, textureId, name)` and
  `pixelForgeStatus()` to the `api` object.
  **Update the exact key list in `test/smoke.js`** to match.
- Add a button **"Edit in Pixel Forge…"** next to each existing Change button:
  - items and blocks: `changeTexture` / `#change-texture`;
  - GUIs: `changeGuiTexture` / `#gui-replace`;
  - armour: `changeArmourSheet` / `#armour-replace-sheet`, only where the sheet is square.
- Keep the same enable rules as the button it sits next to.
- On `saved`:
  - set `state.textureUndo = { entry, textureId, base64: <old base64> }`, like `changeTexture` does;
  - call `refreshAfterTextureChange(entry)`;
  - show the status "Edited <relativePath> in Pixel Forge."
- On `cancelled`: show a neutral status. On `error`: show the error status.
- While waiting: show the status "Editing in Pixel Forge… (save or cancel there to continue)"
  and disable that button. The rest of Grass Block stays usable.

## 4. Tests

- **Unit:** the result/exit-code mapping, the temp-copy cleanup, and rejecting non-square textures before spawning.
- **Hidden end-to-end** (no visible windows; the calling test sets `PIXEL_FORGE_HIDDEN=1`, which
  Pixel Forge honours):
  - `PIXEL_FORGE_TEST_ACTION=paint-save`: the texture in the workspace gets pixel (0,0) = `#FF00FF`,
    a journal entry is recorded, and undo restores the old texture;
  - `cancel`: nothing changes;
  - a non-square texture gives an error and doesn't spawn.
- Skip these tests with a notice when Pixel Forge isn't installed at the detected path.

## 5. House rules

- Add a changelog entry in Way of Flesh `docs/grass-block-changelog.md`.
- Message the "Way-of-Flesh-1.21.X error" session about the change.
- Test mods are read-only: run the e2e test on a scratch copy of the workspace.
