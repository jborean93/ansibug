// Setting a module option to omit removes it, like it would in the playbook.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, waitEnded, setValue }) {
    await openFile('repl.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(7));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    await setValue('data', 'omit');
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(3000);
}
