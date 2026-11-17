// Pause a running playbook, each host stops before its next task starts.
export default async function ({ page, park, startRecording, pause, clickOn, openFile, command }) {
    await openFile('deploy.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await page.keyboard.press('F5');
    await page.locator('.debug-toolbar').waitFor();
    await page.locator('.part.panel').getByText('TASK [Wait for service]').waitFor({ timeout: 60_000 });
    await pause(800);
    await clickOn(page.locator('.debug-toolbar').getByRole('button', { name: /^Pause/ }));
    await park();
    await page.locator('.debug-top-stack-frame-line').waitFor({ timeout: 60_000 });
    await pause(4000);

    await page.keyboard.press('Shift+F5');
    await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
    await pause(1500);
}
