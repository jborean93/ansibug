// The Debug Console suggests the ! commands, module options and variables with a hint for each.
export default async function ({ page, startRecording, pause, click, clickOn, type, openFile, command, gutter }) {
    await openFile('vars.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(9));
    await startRecording();

    await page.keyboard.press('F5');
    await page.locator('.debug-top-stack-frame-line').waitFor({ timeout: 60_000 });
    await pause(1000);
    await page.keyboard.press('Control+Shift+Y');
    await clickOn(page.locator('.repl-input-wrapper'));

    // Each suggest list must close before the next is opened, otherwise waiting for it passes on the old one.
    const suggest = page.locator('.suggest-widget.visible');
    const suggestions = async () => {
        await page.keyboard.press('Control+Space');
        await suggest.waitFor();
        await pause(2500);
    };
    // Tab inserts the suggestion, Enter would run the line in the Debug Console.
    const accept = async (key = 'Tab') => {
        await page.keyboard.press(key);
        await suggest.waitFor({ state: 'hidden' });
    };

    await type('!');
    await suggestions();
    await accept('Escape');
    await type('so ');
    await suggestions();
    await accept();
    await type(' ap');
    await suggestions();
    await accept();
    await type('.name');
    await pause(800);
    await page.keyboard.press('Enter');
    await pause(2500);

    await page.keyboard.press('F5');
    await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
    await pause(1500);
}
