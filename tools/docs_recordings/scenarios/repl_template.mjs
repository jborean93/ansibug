// Template expressions in the Debug Console, with !template or no command at all.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, waitEnded, debugConsole, repl }) {
    await openFile('template.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(9));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1000);
    await debugConsole();
    await repl('my_variable');
    await repl('!template my_variable');
    await repl('my_variable | to_nice_yaml');
    await repl('my_variable.list | join("-")');
    await repl("{'name': my_variable.foo, 'count': my_variable.list | length}");
    await pause(1500);
    await page.keyboard.press('Shift+F5');
    await waitEnded();
    await pause(1500);
}
