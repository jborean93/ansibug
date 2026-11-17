// Remove a module option with !remove_option in the Debug Console.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, waitEnded, debugConsole, repl, showTerminal }) {
    await openFile('repl.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(7));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    await debugConsole();
    await repl('!remove_option data');
    await pause(1000);
    await page.keyboard.press('F5');
    await waitEnded();
    await showTerminal();
    await pause(3000);
}
