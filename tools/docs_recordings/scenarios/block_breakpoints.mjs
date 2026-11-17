// A breakpoint on block can't be set, ones on rescue and always move to the task before them.
export default async function ({ page, startRecording, pause, click, hoverOn, gutter, openFile, command,
    waitStopped, waitEnded }) {
    await openFile('block.yml');
    await command('View: Show Run and Debug');
    await startRecording();

    await click(...await gutter(5));
    await click(...await gutter(8));
    await click(...await gutter(11));
    await pause(1000);
    await page.keyboard.press('F5');
    await waitStopped();
    await pause(1500);
    // The unverified breakpoint explains why in its hover.
    const [x, y] = await gutter(5);
    await page.mouse.move(x, y, { steps: 25 });
    await pause(3000);
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(2500);
}
