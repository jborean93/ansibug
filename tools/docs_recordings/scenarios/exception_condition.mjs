// Set a condition on the Uncaught Failures exception breakpoint so only db1's failure stops.
export default async function ({ page, park, warmUp, startRecording, pause, clickOn, type, openFile, command }) {
    await warmUp();
    await openFile('config.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await clickOn(page.locator('.debug-breakpoints .monaco-list-row', { hasText: 'Uncaught Failures' }), { button: 'right' });
    await clickOn(page.getByRole('menuitem', { name: /^Edit Condition/ }));
    await page.locator('.debug-breakpoints input:focus').waitFor();
    await type("inventory_hostname == 'db1'");
    await pause(800);
    await page.keyboard.press('Enter');
    await park();
    await pause(1000);

    await page.keyboard.press('F5');
    await page.locator('.debug-top-stack-frame-line').waitFor({ timeout: 60_000 });
    await pause(4000);

    await page.keyboard.press('F5');
    await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
    await pause(2000);
}
