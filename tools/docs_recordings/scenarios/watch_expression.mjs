// A watch expression is evaluated again on each stop, foo changes after set_fact.
export default async function ({ page, startRecording, pause, click, clickOn, hoverOn, type, gutter, openFile,
    command, waitStopped, continueToStop, waitEnded, park }) {
    await openFile('watch.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(7));
    await click(...await gutter(10));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1000);
    // The view's actions only show while the mouse is over its header.
    const header = page.locator('.pane-header', { hasText: 'Watch' });
    await hoverOn(header);
    await clickOn(header.getByRole('button', { name: /^Add Expression/ }));
    await page.locator('.debug-watch input:focus').waitFor();
    await type('foo');
    await pause(600);
    await page.keyboard.press('Enter');
    await park();
    await pause(2500);

    await continueToStop();
    await pause(3000);
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(2000);
}
