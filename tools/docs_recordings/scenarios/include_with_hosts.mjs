// A breakpoint in an included file stops once per host, the include task is the frame above it.
// Also takes the call_stack.png and variable_scopes.png stills at the first stop.
export default async function ({ page, startRecording, pause, click, clickOn, gutter, openFile, command,
    waitStopped, continueToStop, waitEnded, park, screenshot }) {
    await openFile('tasks.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(1));
    await openFile('include.yml');
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await park();
    await pause(1500);
    await screenshot('call_stack.png', page.locator('.pane').filter({ has: page.locator('.debug-call-stack') }));
    await screenshot('variable_scopes.png', page.locator('.pane').filter({ has: page.locator('.debug-variables') }));

    const frame = (name) => page.locator('.debug-call-stack .monaco-list-row', { hasText: name });
    await clickOn(frame('include tasks'));
    await pause(2000);
    await clickOn(frame('task inside include'));
    await pause(1500);
    await continueToStop();
    await pause(2500);
    await clickOn(frame('include tasks'));
    await pause(2000);
    await clickOn(frame('task inside include'));
    await pause(1500);
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(2500);
}
