// Add a function breakpoint for any ping module, it stops on that task without a line breakpoint.
export default async function ({ page, park, warmUp, startRecording, pause, clickOn, hoverOn, type, openFile, command }) {
    await warmUp();
    await openFile('install.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    // The view's actions only show while the mouse is over its header.
    const header = page.locator('.pane-header', { hasText: 'Breakpoints' });
    await hoverOn(header);
    await clickOn(header.getByRole('button', { name: 'Add Function Breakpoint' }));
    await page.locator('.debug-breakpoints input:focus').waitFor();
    await type('*.ping');
    await pause(800);
    await page.keyboard.press('Enter');
    await park();
    await pause(1000);

    await page.keyboard.press('F5');
    await page.locator('.debug-top-stack-frame-line').waitFor({ timeout: 60_000 });
    await pause(3500);

    await page.keyboard.press('Shift+F5');
    await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
    await pause(1500);
}
