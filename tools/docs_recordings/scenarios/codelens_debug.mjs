// Debug a playbook with an extra var from its CodeLens, without a launch configuration.
export default async function ({ page, startRecording, pause, clickOn, type, openFile, command, waitEnded }) {
    await openFile('greet.yml');
    await command('View: Show Run and Debug');
    const lens = page.locator('.codelens-decoration').getByText('Debug with Args...');
    await lens.waitFor({ timeout: 30_000 });
    // Enter in a quick input is mislabelled by the key overlay and it's the only key here.
    await startRecording({ keys: false });

    await clickOn(lens);
    await page.locator('.quick-input-widget input:focus').waitFor();
    await pause(800);
    await type('-e my_var=hello');
    await page.keyboard.press('Enter');
    await page.locator('.debug-toolbar').waitFor();
    await waitEnded();
    await pause(3500);
}
