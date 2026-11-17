// A value set in the Variables view is a template, foo without quotes is the variable foo.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, waitEnded, setValue }) {
    await openFile('repl.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(7));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    await setValue('data', 'foo');
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(3000);
}
