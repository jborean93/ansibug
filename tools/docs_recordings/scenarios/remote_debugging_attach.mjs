// Run a playbook with ansibug listen in a terminal standing in for the remote host, attach to it with path
// mappings, then change a module option. Also takes the stepping_options_disconnect.png still.
import fs from 'node:fs';
import path from 'node:path';

export default async function ({ page, startRecording, pause, click, clickOn, textAt, gutter, openFile, command, type,
    waitStopped, waitEnded, setValue, park, screenshot, workspace }) {
    // The "remote" copy of the playbook is at another path, like it would be on the remote host.
    const remote = '/tmp/ansibug-remote';
    fs.rmSync(remote, { recursive: true, force: true });
    fs.cpSync(workspace, remote, { recursive: true });
    fs.mkdirSync(path.join(workspace, '.vscode'), { recursive: true });
    fs.writeFileSync(path.join(workspace, '.vscode', 'launch.json'), JSON.stringify({
        version: '0.2.0',
        configurations: [{
            name: 'Ansibug: Attach to remote ansible-playbook Process',
            type: 'ansible',
            request: 'attach',
            address: 'tcp://localhost:45381',
            pathMappings: [{ localRoot: '${workspaceFolder}/', remoteRoot: `${remote}/` }],
        }],
    }, null, 4));

    await openFile('launch.json');
    await openFile('repl.yml');
    await command('View: Show Run and Debug');
    await command('Terminal: Create New Terminal');
    await page.locator('.part.panel .xterm').waitFor();
    await startRecording();

    await type(`cd ${remote} && python -m ansibug listen --addr tcp://:45381 repl.yml`);
    await page.keyboard.press('Enter');
    await page.locator('.part.panel').getByText(/listener has been configured/).waitFor({ timeout: 60_000 });
    await pause(1500);

    // Show the attach configuration uses the address and port the listener is on, the port is highlighted.
    await clickOn(page.locator('.tab', { hasText: 'launch.json' }));
    const address = page.locator('.editor-group-container .view-line', { hasText: '"address"' });
    const [x, y] = await textAt(address, '45381');
    await page.mouse.move(x, y, { steps: 25 });
    await pause(300);
    await page.mouse.dblclick(x, y);
    await park(); // The address' hover would cover the configuration.
    await pause(3500);
    await clickOn(page.locator('.tab', { hasText: 'repl.yml' }));
    await pause(800);
    await click(...await gutter(7));
    await pause(800);
    await page.keyboard.press('F5');
    await waitStopped();
    await park();
    await pause(1500);
    await screenshot('stepping_options_disconnect.png', page.locator('.debug-toolbar'));
    await setValue('data', "'bar'");
    await page.keyboard.press('F5');
    await waitEnded();
    await pause(3000);
}
