// Breakpoints on lines that aren't the start of a task move to the start of the task before them.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, continueToStop, waitEnded }) {
    await openFile('relocation.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await click(...await gutter(7));
    await click(...await gutter(11));
    await pause(1000);
    await page.keyboard.press('F5');
    await waitStopped();
    await pause(3000);
    await continueToStop();
    await pause(2500);
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(2500);
}
