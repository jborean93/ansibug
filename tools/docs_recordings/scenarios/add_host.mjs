// A host added with add_host only becomes a thread in the next play.
export default async function ({ page, startRecording, pause, click, gutter, openFile, command,
    waitStopped, continueToStop, waitEnded }) {
    await openFile('add_host.yml');
    await command('View: Show Run and Debug');
    await click(...await gutter(9));
    await click(...await gutter(15));
    await startRecording();

    await page.keyboard.press('F5');
    await waitStopped();
    await pause(2500);
    // web1 and web2 in play 1, then web1, web2 and web3 in play 2.
    for (let i = 0; i < 4; i++) {
        await continueToStop();
        await pause(2000);
    }
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(2500);
}
