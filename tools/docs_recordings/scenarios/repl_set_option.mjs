// Add a module option the task doesn't have with !set_option.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, waitEnded, debugConsole, repl, showTerminal }) {
    await openFile('set_option.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(5));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    await debugConsole();
    await repl("!set_option data 'foo'");
    await pause(1000);
    await page.keyboard.press('F5');
    await waitEnded();
    await showTerminal();
    await pause(3000);
}
