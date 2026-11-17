// Add a logpoint with a templated message, the run doesn't stop and each host writes it to the Debug Console.
export default async function ({ page, startRecording, pause, click, clickOn, type, openFile, command, gutter,
    waitEnded, park }) {
    await openFile('install.yml');
    // Without the side bar the template and the Debug Console tab have the whole width.
    await command('View: Toggle Primary Side Bar Visibility');
    await page.locator('.part.sidebar').waitFor({ state: 'hidden' });
    await startRecording({ keys: false });

    await click(...await gutter(7), { button: 'right' });
    await clickOn(page.getByRole('menuitem', { name: /^Add Logpoint/ }));
    await page.locator('.breakpoint-widget .monaco-editor.focused').waitFor();
    await type('{{ inventory_hostname }}: installing {{ packages | length }} packages');
    await page.keyboard.press('Enter');
    await park();
    await pause(800);

    await clickOn(page.locator('.codelens-decoration').getByText('Debug', { exact: true }));
    await page.locator('.debug-toolbar').waitFor();
    await pause(1000);
    // The tab is in the panel's overflow menu when the panel is too narrow to show it.
    const tab = page.locator('.part.panel').getByRole('tab', { name: /^Debug Console/ });
    if (await tab.isVisible()) {
        await clickOn(tab);
    } else {
        await clickOn(page.locator('.part.panel .composite-bar').getByRole('button').last());
        await clickOn(page.getByRole('menuitemcheckbox', { name: /^Debug Console/ })
            .or(page.getByRole('menuitem', { name: /^Debug Console/ })).first());
    }
    await park();
    await page.locator('.repl').getByText('db1: installing 3 packages').waitFor({ timeout: 60_000 });
    await waitEnded();
    await pause(3000);
}
