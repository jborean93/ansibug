# Docs recordings

Regenerates the recordings in `docs/images` by scripting a pinned VS Code inside a container, so every recording has
the same VS Code version, theme, fonts, window size and extension version.

Each recording is `<name>.mp4` and `<name>.png`, its poster frame. The window is 960x600, about the width of the
docs content column, captured at 2x so it is sharp on HiDPI screens and phones when made fullscreen. Embed it with:

```html
<video src="./images/<name>.mp4" poster="./images/<name>.png" width="960" height="600" autoplay loop muted playsinline controls preload="metadata"></video>
```

`controls` lets phone users go fullscreen to read it. The recordings are committed, re-record only the scenarios
whose behaviour or UI changed.

```bash
tools/docs_recordings/run.sh                  # every scenario
tools/docs_recordings/run.sh set_breakpoint   # just these
```

Or run the `docs: regenerate images` task in VS Code. Only `podman` is needed on the host. The first run downloads
VS Code and the ansibug extension into `.cache/`. The ansibug Python code comes from this repo's `src/`.

- `scenarios/<name>.mjs` writes `docs/images/<name>.mp4` and `<name>.png` when it calls `startRecording()`. Setup done
  before that call isn't in the video. A scenario that exports `output = 'gif'` writes `<name>.gif` instead, for the
  README which links to `ansibug_example.gif` on the docs site. `screenshot(file, locator)` saves a still, cropped to
  the locator's element when one is given; `screenshots.mjs` only takes stills.
- Scenarios get a Playwright `page` and the helpers in `record.mjs`, like `openFile`, `command`, `gutter`, `click`,
  `clickOn`, `type`, `setValue`, `debugConsole`, `repl`, `waitStopped`, `continueToStop` and `warmUp`. Prefer
  `getByRole` locators and keyboard shortcuts over VS Code's CSS classes, they change less between versions.
- A click draws a ring where it happened, yellow for a left click and cyan for a right click.
- The key overlay only shows shortcuts like F5, typed text is visible where it's typed. Pass
  `startRecording({ keys: false })` to leave it off.
- `fixtures/` is copied in as the opened workspace: small playbooks, an inventory of dummy hosts that run locally, and
  an `ansible.cfg` with `verbosity = 1` so task results are shown. Keep a playbook short enough to fit the editor,
  about 11 lines while debugging.
- If a scenario fails, a screenshot of that moment is saved to `.cache/<name>-error.png` and the rest still run. A VS Code crash is
  retried once. A recording longer than 2 minutes fails as it has stalled.
- The VS Code and extension versions, settings and window size are pinned at the top of `record.mjs`.
