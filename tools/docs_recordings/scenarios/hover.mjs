// While stopped, hover over a variable path in the playbook to see its value.
export default async function ({ page, startRecording, pause, click, hoverOn, textAt, openFile, command, gutter }) {
    await openFile('vars.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(9));
    await startRecording();

    await page.keyboard.press('F5');
    await page.locator('.debug-top-stack-frame-line').waitFor({ timeout: 60_000 });
    await pause(1500);

    const line = page.locator('.editor-group-container .view-line', { hasText: 'listens on' });
    await page.mouse.move(...await textAt(line, 'ports'), { steps: 25 });
    await page.locator('.debug-hover-widget').waitFor();
    await pause(3000);
    await page.mouse.move(...await textAt(line, 'name'), { steps: 25 });
    await pause(3000);

    await page.keyboard.press('F5');
    await page.locator('.debug-toolbar').waitFor({ state: 'hidden', timeout: 60_000 });
    await pause(1500);
}
