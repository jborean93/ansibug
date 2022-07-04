// The module 'vscode' contains the VS Code extensibility API
// Import the module and reference it with the alias vscode in your code below
import * as vscode from 'vscode';

// this method is called when your extension is activated
// your extension is activated the very first time the command is executed
export function activate(context: vscode.ExtensionContext) {

	console.log('Starting ansibug extension');

	context.subscriptions.push(vscode.commands.registerCommand('ansibug.PickAnsiblePlaybook', config => {
		return vscode.window.showInputBox({
			title: "Enter Ansible Playbook File",
			placeHolder: "Enter the name of the playbook file in the workspace folder",
		});
	}));

	context.subscriptions.push(vscode.commands.registerCommand('ansibug.PickAnsibleProcess', config => {
		return vscode.window.showInputBox({
			title: "Enter Ansible Process Id",
			placeHolder: "Please enter the process id of the ansible-playbook process to debug",
		});
	}));

	context.subscriptions.push(vscode.debug.registerDebugAdapterTrackerFactory('ansibug', {
		createDebugAdapterTracker: (session: vscode.DebugSession): vscode.ProviderResult<vscode.DebugAdapterTracker> => {
			return new MyDebugTracker();
		}
	}));

	context.subscriptions.push(vscode.debug.registerDebugAdapterDescriptorFactory('ansibug', {
		createDebugAdapterDescriptor: (session: vscode.DebugSession) => {
			return new vscode.DebugAdapterExecutable("python", ["/home/jborean/dev/ansibug/debug-stdio.py"])
		}
	}));

	//context.subscriptions.push(vscode.commands.registerCommand('ansibug.RunPlaybook',))

	// context.subscriptions.push(
	// 	vscode.commands.registerCommand('extension.ansibug.runEditorContents', (resource: vscode.Uri) => {
	// 		let targetResource = resource;
	// 		if (!targetResource && vscode.window.activeTextEditor) {
	// 			targetResource = vscode.window.activeTextEditor.document.uri;
	// 		}
	// 		if (targetResource) {
	// 			vscode.debug.startDebugging(undefined, {
	// 				type: 'ansibug',
	// 				name: 'Run File',
	// 				request: 'launch',
	// 				playbook: targetResource.fsPath
	// 			},
	// 				{ noDebug: true }
	// 			);
	// 		}
	// 	}),
	// 	vscode.commands.registerCommand('extension.ansibug.debugEditorContents', (resource: vscode.Uri) => {
	// 		let targetResource = resource;
	// 		if (!targetResource && vscode.window.activeTextEditor) {
	// 			targetResource = vscode.window.activeTextEditor.document.uri;
	// 		}
	// 		if (targetResource) {
	// 			vscode.debug.startDebugging(undefined, {
	// 				type: 'ansibug',
	// 				name: 'Debug File',
	// 				request: 'launch',
	// 				playbook: targetResource.fsPath
	// 			});
	// 		}
	// 	}),
	// );

	// // register a dynamic configuration provider for 'mock' debug type
	// context.subscriptions.push(vscode.debug.registerDebugConfigurationProvider('ansibug', {
	// 	provideDebugConfigurations(folder: vscode.WorkspaceFolder | undefined): vscode.ProviderResult<vscode.DebugConfiguration[]> {
	// 		return [
	// 			{
	// 				name: "Dynamic Launch",
	// 				request: "launch",
	// 				type: "ansibug",
	// 				playbook: "${file}"
	// 			},
	// 			{
	// 				name: "Another Dynamic Launch",
	// 				request: "launch",
	// 				type: "ansibug",
	// 				playbook: "${file}"
	// 			},
	// 			{
	// 				name: "Mock Launch",
	// 				request: "launch",
	// 				type: "ansibug",
	// 				playbook: "${file}"
	// 			}
	// 		];
	// 	},
	// }, vscode.DebugConfigurationProviderTriggerKind.Dynamic));
}

// this method is called when your extension is deactivated
export function deactivate() { }

class MyDebugTracker implements vscode.DebugAdapterTracker {

	onWillStartSession?(): void {
		console.log("Debug Start");
	}

	/**
	 * The debug adapter is about to receive a Debug Adapter Protocol message from VS Code.
	 */
	onWillReceiveMessage?(message: any): void {
		console.log('Debug ToAdapter: ', JSON.stringify(message));
	}
	/**
	 * The debug adapter has sent a Debug Adapter Protocol message to VS Code.
	 */
	onDidSendMessage?(message: any): void {
		console.log('Debug FromAdapter: ', JSON.stringify(message));
	}
	/**
	 * The debug adapter session is about to be stopped.
	 */
	onWillStopSession?(): void {
		console.log("Debug Stop");
	}
	/**
	 * An error with the debug adapter has occurred.
	 */
	onError?(error: Error): void {
		console.log("Debug Error: ", error.message, error.stack);
	}
	/**
	 * The debug adapter has exited with the given exit code or signal.
	 */
	onExit?(code: number | undefined, signal: string | undefined): void {
		console.log("Debug Exit: ", code?.toString());
	}
}
