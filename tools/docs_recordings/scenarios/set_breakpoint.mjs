// Set a breakpoint on a task, start debugging with F5, stop on it, then continue to the end.
export default async function ({ page, startRecording, pause, poster, click, clickOn, command, openFile, gutter }) {
    await openFile('main.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await click(...await gutter(5));
    await pause(1000);

    await page.keyboard.press('F5');
    await page.locator('.debug-top-stack-frame-line').waitFor({ timeout: 60_000 });
    await pause(1000);
    await poster();
    await pause(2000);

    // Matched by its accessible name, which is "Continue (F5)".
    await clickOn(page.locator('.debug-toolbar').getByRole('button', { name: /^Continue/ }));
    await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
    await pause(3000);
}
