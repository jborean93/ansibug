// The docs stills that aren't from a recording: the exception breakpoints, the debug toolbar while stopped, a
// stop on a failed task, and the launch.json snippets.
import fs from 'node:fs';
import path from 'node:path';

export default async function ({ page, pause, click, gutter, openFile, command, waitStopped, waitEnded,
    warmUp, park, screenshot, workspace }) {
    // An empty launch.json for the snippets still at the end, written now so Quick Open has it indexed. With no
    // configurations F5 still launches the current file.
    fs.mkdirSync(path.join(workspace, '.vscode'), { recursive: true });
    fs.writeFileSync(path.join(workspace, '.vscode', 'launch.json'),
        '{\n    "version": "0.2.0",\n    "configurations": [\n        \n    ]\n}\n');

    await command('View: Show Run and Debug');
    await warmUp();
    await park();
    await screenshot('exception_breakpoints.png', page.locator('.pane').filter({ has: page.locator('.debug-breakpoints') }));

    await openFile('main.yml');
    await click(...await gutter(5));
    await page.keyboard.press('F5');
    await waitStopped();
    await park();
    await pause(1000);
    await screenshot('stepping_options_stop.png', page.locator('.debug-toolbar'));
    await page.keyboard.press('Shift+F5');
    await waitEnded();

    await openFile('crash.yml');
    await page.keyboard.press('F5');
    await waitStopped();
    await page.locator('.exception-widget').waitFor();
    await park();
    await pause(1500);
    await screenshot('exception_breakpoints_fired.png');
    await page.keyboard.press('Shift+F5');
    await waitEnded();

    // The cursor in the empty configurations list, showing the snippets, with only launch.json open.
    await command('View: Close All Editors');
    await openFile('launch.json');
    await page.keyboard.press('Control+G');
    await page.keyboard.type('4');
    await page.keyboard.press('Enter');
    await page.keyboard.press('End');
    if (await page.locator('.part.panel').isVisible()) await page.keyboard.press('Control+J');
    // The button VS Code shows in launch.json, it lists the snippets like Ctrl+Space once JSON support is ready.
    await page.getByText('Add Configuration...').click();
    const suggest = page.locator('.suggest-widget.visible');
    await suggest.waitFor({ timeout: 60_000 });
    // Highlight the snippet the docs talk about, wherever it is in the list.
    const launchCurrent = suggest.locator('.monaco-list-row.focused', { hasText: 'Launch Current File' });
    for (let i = 0; i < 30 && !(await launchCurrent.isVisible()); i++) {
        await page.keyboard.press('ArrowDown');
    }
    await launchCurrent.waitFor();
    await pause(1000);
    await park();
    await screenshot('vscode_launch_configuration.png', page.locator('.part.editor'));
}
