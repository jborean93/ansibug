// Add a conditional breakpoint so it only stops for web2, then remove it.
export default async function ({ page, startRecording, pause, click, clickOn, type, gutter, openFile, command,
    waitStopped, waitEnded, park }) {
    await openFile('conditional.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await click(...await gutter(5), { button: 'right' });
    await clickOn(page.getByRole('menuitem', { name: /^Add Conditional Breakpoint/ }));
    await page.locator('.breakpoint-widget .monaco-editor.focused').waitFor();
    await type("inventory_hostname == 'web2'");
    await pause(800);
    await page.keyboard.press('Enter');
    await park();
    await pause(800);

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(3500);
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(1500);

    await click(...await gutter(5), { button: 'right' });
    await clickOn(page.getByRole('menuitem', { name: /^Remove Breakpoint/ }));
    await park();
    await pause(1500);
}
