// Add a host variable with !set_hostvar that a later task uses.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, waitEnded, debugConsole, repl, showTerminal }) {
    await openFile('hostvar.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(5));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    await debugConsole();
    await repl('foo');
    await repl("!set_hostvar foo 'bar'");
    await repl('foo');
    await page.keyboard.press('F5');
    await waitEnded();
    await showTerminal();
    await pause(3000);
}
