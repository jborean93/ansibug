// A loop task stops once, not per item, and Step Over goes to the next task.
export default async function ({ page, startRecording, pause, click, clickOn, gutter, openFile, command,
    waitStopped, waitEnded, park }) {
    await openFile('loop.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(5));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    await clickOn(page.locator('.debug-toolbar').getByRole('button', { name: /^Step Over/ }));
    await park();
    await page.locator('.part.panel').getByText('TASK [task 2]').waitFor({ timeout: 60_000 });
    await waitStopped();
    await pause(3500);
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(2000);
}
