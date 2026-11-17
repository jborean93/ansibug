// Add a breakpoint with a hit count of 2, every host reaching the task is a hit so it only stops on the second host.
export default async function ({ page, startRecording, pause, click, clickOn, type, openFile, command, gutter }) {
    await openFile('install.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await click(...await gutter(10), { button: 'right' });
    await clickOn(page.getByRole('menuitem', { name: /^Add Conditional Breakpoint/ }));
    const widget = page.locator('.breakpoint-widget');
    await clickOn(widget.locator('select, .monaco-select-box').first());
    await clickOn(page.locator('.monaco-select-box-dropdown-container').getByText('Hit Count', { exact: true }));
    await clickOn(widget.locator('.inputContainer'));
    await type('2');
    await pause(800);
    await page.keyboard.press('Enter');
    await pause(1000);

    await page.keyboard.press('F5');
    await page.locator('.debug-top-stack-frame-line').waitFor({ timeout: 60_000 });
    await pause(3500);

    await page.keyboard.press('F5');
    await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
    await pause(2000);
}
