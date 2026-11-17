// Records each scenarios/<name>.mjs against a pinned VS Code and writes docs/images/<name>.mp4 and <name>.png, the
// poster frame.
// Run through run.sh so it is inside the container (Xvfb, fonts, ffmpeg, Ansible).
// Usage: node record.mjs [name ...]   (no names records every scenario)
import { downloadAndUnzipVSCode, resolveCliArgsFromVSCodeExecutablePath } from '@vscode/test-electron';
import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { _electron as electron } from 'playwright';

const VSCODE_VERSION = '1.145.3';
const EXTENSION_VERSION = '0.3.0';
// The window size in CSS pixels, captured at SCALE times that so it stays sharp on HiDPI screens. 960 wide is about
// the docs content column, see README.md.
const SIZE = { width: 960, height: 600 };
const SCALE = 2;
// Height of the bottom panel (terminal, debug console) in CSS pixels.
const PANEL_HEIGHT = 240;
// A recording longer than this has stalled, like the machine sleeping, so it fails rather than writing a huge video.
const MAX_SECONDS = 120;

const here = import.meta.dirname;
const imagesDir = path.resolve(here, '..', '..', 'docs', 'images');
const cacheDir = path.join(here, '.cache');

const SETTINGS = {
    'workbench.colorTheme': 'Default Dark Modern',
    'workbench.startupEditor': 'none',
    'workbench.tips.enabled': false,
    'workbench.enableExperiments': false,
    'workbench.layoutControl.enabled': false,
    'window.titleBarStyle': 'custom',
    'window.restoreWindows': 'none',
    'window.commandCenter': false,
    'editor.fontFamily': 'DejaVu Sans Mono',
    'editor.fontSize': 15,
    'editor.minimap.enabled': false,
    // Suggestions popping up and brackets closing themselves while a template is typed distract from it, Ctrl+Space
    // still shows suggestions.
    'editor.quickSuggestions': { other: 'off', comments: 'off', strings: 'off' },
    'editor.suggestOnTriggerCharacters': false,
    'editor.wordBasedSuggestions': 'off',
    'editor.autoClosingBrackets': 'never',
    'editor.autoClosingQuotes': 'never',
    // It pins a line over the top of the editor when scrolled, covering the line under it.
    'editor.stickyScroll.enabled': false,
    'terminal.integrated.fontFamily': 'DejaVu Sans Mono',
    // Ansible never draws its banners narrower than 79 columns, this fits 80+ in the panel so they don't wrap.
    'terminal.integrated.fontSize': 13,
    'terminal.integrated.tabs.enabled': false,
    'terminal.integrated.defaultProfile.linux': 'bash',
    // A new terminal doesn't otherwise get the container's PATH and PYTHONPATH with Ansible and ansibug.
    'terminal.integrated.env.linux': { PATH: process.env.PATH, PYTHONPATH: process.env.PYTHONPATH },
    'terminal.integrated.profiles.linux': {
        bash: { path: 'bash', args: ['--norc', '--noprofile'], env: { PS1: '$ ' } },
    },
    'workbench.secondarySideBar.defaultVisibility': 'hidden',
    'chat.disableAIFeatures': true,
    'telemetry.telemetryLevel': 'off',
    'update.mode': 'none',
    'extensions.autoUpdate': false,
    'extensions.autoCheckUpdates': false,
    'extensions.ignoreRecommendations': true,
    'git.enabled': false,
    'security.workspace.trust.enabled': false,
    'files.hotExit': 'off',
    // Screencast mode shows the keys pressed, it is turned on by startRecording.
    'screencastMode.fontSize': 28,
    'screencastMode.keyboardOverlayTimeout': 1500,
    // Only shortcuts like F5 or Ctrl+Space, typed text like a template is already visible where it's typed.
    'screencastMode.keyboardOptions': {
        showKeys: false, showKeybindings: true, showCommands: false, showCommandGroups: false,
        showSingleEditorCursorMoves: false,
    },
    // Its click indicator only shows while the button is held, injectCursor draws a clearer one.
    'screencastMode.mouseIndicatorColor': '#00000000',
    'ansibug.interpreterPath': '/opt/ansible/bin/python',
};

async function setup() {
    fs.mkdirSync(cacheDir, { recursive: true });
    const vscode = await downloadAndUnzipVSCode({ version: VSCODE_VERSION, cachePath: path.join(cacheDir, 'vscode') });

    const extensionsDir = path.join(cacheDir, `extensions-${EXTENSION_VERSION}`);
    if (!fs.existsSync(extensionsDir)) {
        const vsix = path.join(cacheDir, `ansibug-${EXTENSION_VERSION}.vsix`);
        const url = `https://open-vsx.org/api/jborean/ansibug/${EXTENSION_VERSION}/file/jborean.ansibug-${EXTENSION_VERSION}.vsix`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`Failed to download ${url}: ${res.status}`);
        fs.writeFileSync(vsix, Buffer.from(await res.arrayBuffer()));

        const [cli, ...cliArgs] = resolveCliArgsFromVSCodeExecutablePath(vscode, { reuseMachineInstall: true });
        const installArgs = ['--extensions-dir', extensionsDir, '--user-data-dir', path.join(cacheDir, 'install-user-data')];
        execFileSync(cli, [...cliArgs, ...installArgs, '--install-extension', vsix], {
            stdio: 'inherit',
        });
    }
    return { vscode, extensionsDir };
}

// The capture has no mouse cursor, this draws one that follows the real mouse events and a ring that expands from
// each click like screen recorders do.
function injectCursor() {
    const svgNs = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNs, 'svg');
    svg.setAttribute('width', '20');
    svg.setAttribute('height', '24');
    svg.setAttribute('viewBox', '0 0 20 24');
    Object.assign(svg.style, {
        position: 'fixed', left: '-50px', top: '-50px', zIndex: '2147483647',
        pointerEvents: 'none', transition: 'transform 80ms',
    });
    const arrow = document.createElementNS(svgNs, 'path');
    arrow.setAttribute('d', 'M1 1 L1 19 L6 14.5 L9.5 22 L12.5 20.7 L9 13.5 L15.5 13.5 Z');
    arrow.setAttribute('fill', 'white');
    arrow.setAttribute('stroke', 'black');
    arrow.setAttribute('stroke-width', '1.4');
    svg.appendChild(arrow);
    document.body.appendChild(svg);

    const opts = { capture: true, passive: true };
    document.addEventListener('mousemove', (e) => {
        svg.style.left = `${e.clientX - 1}px`;
        svg.style.top = `${e.clientY - 1}px`;
    }, opts);
    document.addEventListener('mousedown', (e) => {
        svg.style.transform = 'scale(0.8)';
        // Yellow for a left click, cyan for a right click.
        const colour = e.button === 2 ? '#3ec5ff' : '#ffcc00';
        const ring = document.createElement('div');
        Object.assign(ring.style, {
            position: 'fixed', left: `${e.clientX - 20}px`, top: `${e.clientY - 20}px`, width: '40px', height: '40px',
            boxSizing: 'border-box', borderRadius: '50%', border: `4px solid ${colour}`, background: `${colour}40`,
            zIndex: '2147483646', pointerEvents: 'none',
        });
        document.body.appendChild(ring);
        ring.animate(
            [{ transform: 'scale(0.3)', opacity: 1 }, { transform: 'scale(1.4)', opacity: 0 }],
            { duration: 600, easing: 'ease-out' },
        ).onfinish = () => ring.remove();
    }, opts);
    document.addEventListener('mouseup', () => { svg.style.transform = ''; }, opts);
}

// Grabs the top left of the Xvfb display, where the window is placed. Playwright's own recordVideo stalls the
// VS Code window from loading so isn't used.
function startCapture(file) {
    const ffmpeg = spawn('ffmpeg', [
        '-y', '-loglevel', 'error', '-f', 'x11grab', '-draw_mouse', '0', '-framerate', '25',
        '-video_size', `${SIZE.width * SCALE}x${SIZE.height * SCALE}`, '-i', `${process.env.DISPLAY}+0,0`,
        '-c:v', 'libx264rgb', '-preset', 'ultrafast', '-crf', '0', file,
    ], { stdio: ['pipe', 'inherit', 'inherit'] });
    const exited = new Promise((resolve, reject) => {
        ffmpeg.on('exit', (code) => (code === 0 ? resolve() : reject(new Error(`ffmpeg capture exited ${code}`))));
    });
    const started = Date.now();
    return async () => {
        ffmpeg.stdin.end('q');
        await exited;
        const seconds = (Date.now() - started) / 1000;
        if (seconds > MAX_SECONDS) throw new Error(`Recording took ${seconds}s, more than ${MAX_SECONDS}s, it stalled`);
    };
}

async function record(name, { vscode, extensionsDir }) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), `ansibug-${name}-`));
    // A fixed path as it is visible in the title bar and terminal.
    const workspace = path.join(os.homedir(), 'ansibug-demo');
    fs.rmSync(workspace, { recursive: true, force: true });
    const userData = path.join(tmp, 'user-data');
    const video = path.join(tmp, 'capture.mkv');
    const poster = path.join(imagesDir, `${name}.png`);
    let posterTaken = false;
    let scenarioOutput = 'mp4';
    fs.cpSync(path.join(here, 'fixtures'), workspace, { recursive: true });
    fs.mkdirSync(path.join(userData, 'User'), { recursive: true });
    fs.writeFileSync(path.join(userData, 'User', 'settings.json'), JSON.stringify(SETTINGS, null, 4));

    const app = await electron.launch({
        executablePath: vscode,
        args: [
            workspace,
            `--user-data-dir=${userData}`,
            `--extensions-dir=${extensionsDir}`,
            '--disable-workspace-trust',
            '--skip-welcome',
            '--skip-release-notes',
            '--disable-telemetry',
            '--disable-updates',
            '--password-store=basic',
            '--no-sandbox',
            `--force-device-scale-factor=${SCALE}`,
        ],
    });

    let stopCapture;
    try {
        const page = await app.firstWindow();
        // There is no window manager under Xvfb so the bounds are exact and undecorated.
        await app.evaluate(({ BrowserWindow }, size) => {
            BrowserWindow.getAllWindows()[0].setBounds({ x: 0, y: 0, ...size });
        }, SIZE);
        await page.locator('.monaco-workbench').waitFor();
        await page.evaluate(injectCursor);
        const quickInput = page.locator('.quick-input-widget');

        // There's no setting for the panel height, drag its top edge then hide it. VS Code reopens it at that height.
        const panel = page.locator('.part.panel');
        // Opened on Problems as Ctrl+J would start a terminal, whose tab list then takes width from the debug one.
        await page.keyboard.press('Control+Shift+M');
        await panel.waitFor();
        const box = await panel.boundingBox();
        const x = box.x + box.width / 2;
        const statusBar = await page.locator('.part.statusbar').boundingBox();
        await page.mouse.move(x, box.y - 1);
        await page.mouse.down();
        await page.mouse.move(x, statusBar.y - PANEL_HEIGHT, { steps: 5 });
        await page.mouse.up();
        await page.keyboard.press('Control+J');
        await panel.waitFor({ state: 'hidden' });

        const ctx = {
            page,
            // Starts the video capture, call it once the setup the viewer needn't see is done.
            // keys: false leaves the key overlay off, for a recording driven by the mouse and typing where the only
            // keys shown would be Enter in a quick input, which screencast mode mislabels.
            startRecording: async ({ keys = true } = {}) => {
                if (keys) await ctx.command('Developer: Toggle Screencast Mode');
                await page.waitForTimeout(2000); // Lets the keys used to turn it on fade out.
                stopCapture = startCapture(video);
            },
            pause: (ms = 1000) => page.waitForTimeout(ms),
            // Moves the mouse in visible steps rather than teleporting.
            moveTo: async (x, y) => page.mouse.move(x, y, { steps: 25 }),
            // Moves to the point then holds the button briefly so the click is visible. button can be 'right'.
            click: async (x, y, { button = 'left' } = {}) => {
                await page.mouse.move(x, y, { steps: 25 });
                await page.waitForTimeout(300);
                await page.mouse.down({ button });
                await page.waitForTimeout(150);
                await page.mouse.up({ button });
            },
            // Same as click but on the centre of a Playwright locator, waiting for it to be visible first.
            clickOn: async (locator, opts) => {
                await locator.waitFor();
                const box = await locator.boundingBox();
                await ctx.click(box.x + box.width / 2, box.y + box.height / 2, opts);
            },
            // Moves the mouse onto a locator and leaves it there, for hovers.
            hoverOn: async (locator) => {
                await locator.waitFor();
                const box = await locator.boundingBox();
                await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 25 });
            },
            // The point in the glyph margin, where breakpoints are drawn, for a line of the active editor.
            gutter: async (line) => {
                const number = page.locator('.editor-group-container .monaco-editor .line-numbers', {
                    hasText: new RegExp(`^${line}$`),
                });
                const box = await number.boundingBox();
                return [box.x - 8, box.y + box.height / 2];
            },
            // Runs main.yml once so VS Code knows the exception breakpoints and shows the Breakpoints view, then
            // hides what that run left behind. Call it before startRecording.
            warmUp: async () => {
                await ctx.openFile('main.yml');
                await page.keyboard.press('F5');
                await page.locator('.debug-toolbar').waitFor();
                await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
                await ctx.command('Terminal: Kill All Terminals');
                await ctx.command('View: Close All Editors');
                if (await page.locator('.part.panel').isVisible()) await page.keyboard.press('Control+J');
                await page.locator('.part.panel').waitFor({ state: 'hidden' });
            },
            // The centre of the first occurrence of text inside the element of a locator, for text that isn't its own
            // element like part of a line in the editor.
            textAt: async (locator, text) => {
                await locator.waitFor();
                return locator.evaluate((el, text) => {
                    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
                    let content = '';
                    const nodes = [];
                    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
                        nodes.push([n, content.length]);
                        content += n.data;
                    }
                    const start = content.indexOf(text);
                    if (start === -1) throw new Error(`'${text}' not found in '${content}'`);
                    const pos = (offset) => {
                        const [node, base] = nodes.findLast(([, b]) => b <= offset);
                        return [node, offset - base];
                    };
                    const range = document.createRange();
                    range.setStart(...pos(start));
                    range.setEnd(...pos(start + text.length - 1));
                    const r = range.getBoundingClientRect();
                    return [r.x + r.width / 2, r.y + r.height / 2];
                }, text);
            },
            // Moves the mouse to an empty part of the editor so the tooltip it was over doesn't stay on screen.
            park: () => page.mouse.move(SIZE.width - 40, SIZE.height - PANEL_HEIGHT - 50, { steps: 15 }),
            // Waits for the session to stop on a task, or for it to end.
            waitStopped: () => page.locator('.debug-top-stack-frame-line').first().waitFor({ timeout: 60_000 }),
            waitEnded: () => page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 }),
            // Continues with F5 and waits for the next stop, the current one has to clear first.
            continueToStop: async () => {
                await page.keyboard.press('F5');
                await page.locator('.debug-top-stack-frame-line').first().waitFor({ state: 'hidden', timeout: 10_000 })
                    .catch(() => {}); // It can stop again faster than this checks.
                await ctx.waitStopped();
            },
            // Right click a variable whose row starts with name, Set Value, and enter value.
            setValue: async (name, value) => {
                const row = page.locator('.debug-variables .monaco-list-row', { hasText: new RegExp(`^\\s*${name}\\b`) });
                await ctx.clickOn(row.first(), { button: 'right' });
                await ctx.clickOn(page.getByRole('menuitem', { name: /^Set Value/ }));
                await page.locator('.debug-variables input:focus').waitFor();
                await page.keyboard.press('Control+A');
                await ctx.type(value);
                await page.waitForTimeout(600);
                await page.keyboard.press('Enter');
                await page.waitForTimeout(1200);
            },
            // Shows the Debug Console and focuses its input, then runs a line in it.
            debugConsole: async () => {
                await page.keyboard.press('Control+Shift+Y');
                await page.locator('.repl-input-wrapper').waitFor();
                await page.locator('.repl-input-wrapper').click();
            },
            repl: async (text) => {
                await ctx.type(text);
                await page.waitForTimeout(600);
                await page.keyboard.press('Enter');
                await page.waitForTimeout(1500);
            },
            // The Terminal tab can be in the panel's overflow menu, the shortcut always reaches it.
            showTerminal: () => page.keyboard.press('Control+`'),
            // Types at a speed a viewer can follow, then holds so what was typed can be read before it's used.
            type: async (text) => {
                await page.keyboard.type(text, { delay: 110 });
                await page.waitForTimeout(1500);
            },
            command: async (title) => {
                await page.keyboard.press('Control+Shift+P');
                await quickInput.waitFor();
                await page.keyboard.type(title);
                await page.locator('.quick-input-list .monaco-list-row.focused').waitFor();
                await page.keyboard.press('Enter');
                await quickInput.waitFor({ state: 'hidden' });
            },
            openFile: async (file) => {
                await page.keyboard.press('Control+P');
                await quickInput.waitFor();
                await page.keyboard.type(file);
                await page.locator('.quick-input-list .monaco-list-row.focused', { hasText: file }).waitFor();
                await page.keyboard.press('Enter');
                await page.locator('.tab.active', { hasText: file }).waitFor();
                // A playbook's CodeLens renders a moment later and moves every line down, wait for it so a line's
                // position doesn't change between finding and clicking it.
                if (file.endsWith('.yml')) {
                    await page.locator('.editor-group-container .codelens-decoration').first()
                        .waitFor({ timeout: 15_000 }).catch(() => {}); // A tasks file has none.
                }
            },
            // Saves a still to docs/images, cropped to a locator's element when one is given. It is grabbed from the
            // display like the videos, Playwright's screenshots can crash VS Code's renderer.
            screenshot: async (file, locator) => {
                let { x, y, width, height } = { x: 0, y: 0, ...SIZE };
                if (locator) {
                    await locator.waitFor();
                    ({ x, y, width, height } = await locator.boundingBox());
                }
                const px = (v) => Math.round(v * SCALE);
                execFileSync('ffmpeg', [
                    '-y', '-loglevel', 'error', '-f', 'x11grab', '-draw_mouse', '0',
                    '-video_size', `${px(width)}x${px(height)}`, '-i', `${process.env.DISPLAY}+${px(x)},${px(y)}`,
                    '-frames:v', '1', path.join(imagesDir, file),
                ]);
            },
            // The workspace folder, for a scenario that needs to write a file like .vscode/launch.json.
            workspace,
            // Saves the current screen as the video's poster, shown before it plays. Defaults to the last frame.
            poster: async () => { await page.screenshot({ path: poster }); posterTaken = true; },
        };
        const scenario = await import(path.join(here, 'scenarios', `${name}.mjs`));
        // A scenario exports output = 'gif' to write a GIF instead of a video and poster.
        scenarioOutput = scenario.output ?? 'mp4';
        try {
            await scenario.default(ctx);
        } catch (err) {
            // Best effort, failing to capture it mustn't hide the original error.
            try {
                execFileSync('ffmpeg', [
                    '-y', '-loglevel', 'error', '-f', 'x11grab', '-video_size', `${SIZE.width * SCALE}x${SIZE.height * SCALE}`,
                    '-i', `${process.env.DISPLAY}+0,0`, '-frames:v', '1', path.join(cacheDir, `${name}-error.png`),
                ]);
            } catch {}
            throw err;
        }
    } finally {
        try {
            await stopCapture?.();
        } finally {
            // VS Code can hold its window open, like on a running debug session, so don't wait on it forever.
            const closed = app.close();
            const timedOut = await Promise.race([
                closed.then(() => false),
                new Promise((r) => setTimeout(() => r(true), 15_000)),
            ]);
            if (timedOut) app.process().kill('SIGKILL');
        }
    }

    if (stopCapture && scenarioOutput === 'gif') {
        // A GIF for places that can't play a video, like the README on GitHub, at 1x to keep it small.
        const gif = path.join(imagesDir, `${name}.gif`);
        execFileSync('ffmpeg', [
            '-y', '-loglevel', 'error', '-i', video,
            '-vf', `fps=12,scale=${SIZE.width}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=none:diff_mode=rectangle`,
            gif,
        ]);
        console.log(`Wrote ${path.relative(process.cwd(), gif)}`);
    } else if (stopCapture) {
        const mp4 = path.join(imagesDir, `${name}.mp4`);
        // yuv420p and faststart so every browser plays it and can start before it has fully downloaded.
        execFileSync('ffmpeg', [
            '-y', '-loglevel', 'error', '-i', video,
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '24', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            mp4,
        ]);
        if (!posterTaken) {
            execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-sseof', '-0.5', '-i', video, '-update', '1', poster]);
        }
        console.log(`Wrote ${path.relative(process.cwd(), mp4)} and ${path.basename(poster)}`);
    }
    fs.rmSync(tmp, { recursive: true, force: true });
}

const names = process.argv.slice(2);
const all = fs.readdirSync(path.join(here, 'scenarios')).filter((f) => f.endsWith('.mjs')).map((f) => f.slice(0, -4));
const selected = names.length ? names : all;
const unknown = selected.filter((n) => !all.includes(n));
if (unknown.length) throw new Error(`Unknown scenario(s): ${unknown.join(', ')}. Known: ${all.join(', ')}`);

const env = await setup();
const failed = [];
for (const name of selected) {
    console.log(`Recording ${name}`);
    try {
        try {
            await record(name, env);
        } catch (err) {
            // VS Code's renderer occasionally crashes under Xvfb, that is retried once rather than the scenario.
            if (!/Target crashed|has been closed/.test(err.message)) throw err;
            console.log(`VS Code crashed recording ${name}, retrying`);
            await record(name, env);
        }
    } catch (err) {
        console.error(`${name} failed, see .cache/${name}-error.png:\n${err.stack}`);
        failed.push(name);
    }
}
if (failed.length) {
    console.error(`Failed: ${failed.join(' ')}`);
    process.exit(1);
}
