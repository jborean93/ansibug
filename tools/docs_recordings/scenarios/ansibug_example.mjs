// The README overview: stop on a breakpoint, change a module option, continue and see the changed result.
// A GIF as GitHub won't play a video in the README, which links to it on the docs site by this name.
export const output = 'gif';

export default async function ({ page, startRecording, pause, click, clickOn, gutter, openFile, command,
    waitStopped, waitEnded, setValue }) {
    await openFile('main.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await click(...await gutter(5));
    await pause(800);
    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    await setValue('data', "'other value'");
    await clickOn(page.locator('.debug-toolbar').getByRole('button', { name: /^Continue/ }));
    await waitEnded();
    await pause(3000);
}
