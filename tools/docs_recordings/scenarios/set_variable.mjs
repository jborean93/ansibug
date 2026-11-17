// Set a module option to a new value from the Variables view before the task runs.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, waitEnded, setValue }) {
    await openFile('repl.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(7));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    await setValue('data', "'other value'");
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(3000);
}
