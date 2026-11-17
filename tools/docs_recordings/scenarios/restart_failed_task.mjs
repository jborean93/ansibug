// A task fails, restart it from the Call Stack, then fix its module option while it is stopped before re-running.
export default async function ({ page, park, startRecording, pause, clickOn, openFile, command, waitStopped,
    waitEnded, setValue }) {
    await openFile('restart.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(3000);

    const frame = page.locator('.debug-call-stack .monaco-list-row', { hasText: 'Read app config' });
    await clickOn(frame, { button: 'right' });
    await clickOn(page.getByRole('menuitem', { name: /^Restart Frame/ }));
    await park();
    // It stops again before the task re-runs, with the module options ready to change.
    await page.locator('.debug-call-stack .monaco-list-row', { hasText: /restarted/i }).waitFor({ timeout: 30_000 });
    await pause(2000);

    const src = page.locator('.debug-variables .monaco-list-row', { hasText: /^\s*src\b/ });
    if (!(await src.isVisible())) {
        await clickOn(page.locator('.debug-variables .monaco-list-row', { hasText: 'Module Options' }));
    }
    await setValue('src', "'/etc/hostname'");
    await pause(1000);

    await page.keyboard.press('F5');
    await waitEnded();
    await pause(3000);
}
