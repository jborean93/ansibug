// Add a nested variable to the Watch view, it is added as an expression that can be evaluated again later.
export default async function ({ page, startRecording, pause, click, clickOn, type, openFile, command, gutter }) {
    await openFile('vars.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(9));
    await startRecording();

    await page.keyboard.press('F5');
    await page.locator('.debug-top-stack-frame-line').waitFor({ timeout: 60_000 });
    await pause(1000);

    // A variable row's text starts with its name.
    const row = (name) => page.locator('.debug-variables .monaco-list-row', { hasText: name }).first();
    await clickOn(page.locator('.debug-variables .monaco-list-row', { hasText: 'Task Variables' }));
    // The list only renders the rows in view, typing the name jumps to it like it would for a user.
    await type('app');
    await pause(500);
    await clickOn(row(/^\s*app\b/));
    // The pane is short, jumping to a row by typing its name or with the arrow keys scrolls it into view.
    await type('ports');
    await pause(500);
    await clickOn(row(/^\s*ports\b/));
    await page.keyboard.press('ArrowDown');
    await clickOn(row(/^\s*0\b/), { button: 'right' });
    await clickOn(page.getByRole('menuitem', { name: /^Add to Watch/ }));
    await page.locator('.debug-watch .monaco-list-row').first().waitFor();
    await pause(3500);

    await page.keyboard.press('F5');
    await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
    await pause(1500);
}
