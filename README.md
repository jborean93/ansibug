# Ansibug

POC for an Ansible Debug Adapter Protocol Runner debugger.

# Workflow

VSCode will use the [DebugAdapterExecutable](https://vshaxe.github.io/vscode-extern/vscode/DebugAdapterExecutable.html) to launch `python -m ansibug dap`.
This entrypoint will use the stdout and stdin to communicate with VSCode and runs locally.
It expects the following messages as defined in DAP:

+ [InitializeRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Initialize)
  + Contains the capabilities of the VSCode client
  + Responds with the `InitializeResponse` that contains the capabilities of `ansibug`
+ [LaunchRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Launch)
  + Contains the VSCode launch.json configuration that is being run
  + The structure is dependent on the VSCode plugin but the following launch modes are defined
    + `Launch`
    + `Attach by PID`
    + `Attach by Socket`
    + `Listen` - maybe not wanted or stretch goal
+ [DisconnectRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Disconnect)
  + Sent at the end of the debugging session
  + Responds with the `DisconnectResponse`

The 3 launch modes are details below.

## Launch

Sent by VSCode when the `launch` request type is specified.
This request type is used to start a new `ansible-playbook` process locally and debug it.
The `arguments` attribute of the request contains the following:

```json
{
  "name": "Ansible: Launch ansible-playbook Process",
  "type": "ansibug",
  "request": "launch",
  "playbook": "main.yml",
  "__configurationTarget": 5,
  "__sessionId": "eedc056d-4f29-48a1-8fbf-887984be2964"
}
```

The `ansibug` DAP server will do the following in response to this message:

+ Bind a new socket on localhost
+ Send a [RunInTerminalRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Reverse_Requests_RunInTerminal)
  + Will request VSCode to spawn `python -m ansibug launch --connect localhost:1234 ...`
  + Expects a `RunInTerminalResponse` with the process id or shell id of the spawned ansible-playbook process
  + The spawned process will start `ansible-playbook` using the args specified and connect to `localhost:1234`
+ There is now a socket that the DAP server and ansible-playbook process can communicate with
  + The DAP server will continue to receive messages over stdin but will act as a middle man to `ansible-playbook`

## Attach by PID

Sent by VSCode when the `attach` request with a `processId` is specified.
This request type is used to attach to an existing `ansible-playbook` process locally and debug it.
The target process can be spawned with `python -m ansibug launch ...` which does all the magic to set up the required plugins for ansibug.
This command starts the `ansible-playbook` process with the required options set so it starts in socket listen mode.

The `ansibug` DAP server will do the following in response to this message:

+ Read file `/tmp/ANSIBUG-{pid}` to get the socket addr used.
+ Connect to the socket specified.
+ Relay all subsequent messages to the socket.

_note: `python -m ansibug launch ...` isn't strictly needed, as long as `ansible-playbook` was spawned with the ansibug collection plugins this will work._

## Attach by Socket

Sent by VSCode when the `attach` request with a socket addr is specified.
This request type is used to attach to an existing `ansible-playbook` process on a remote host.
The target process must be spawned by `python -m ansibug launch --listen 0.0.0.0:1234 ...` as it will bind to a socket to relay communication to the `ansible-playbook` UDS pipe.

The `ansibug` DAP server will do the following in response to this message:

+ Attemp to connect to the addr specified
+ Relay all subsequent messages to the socket

## Listen

This is hypothetical, not sure if it will be possible.
VSCode will sent this request that is going to wait until an `ansibug` process connects to it.
The `ansible-playbook` process is started through `python -m ansibug launch --connect hostname:1234 ...`.
This spawns the `ansible-playbook` process and have it communicate with the DAP server.
The DAP server will then relay the subsequent messages exchanged over the socket back to VSCode.

This is essentially the same as `Launch` except it waits until the `ansibug` process is manually started rather than starting it itself.

# Communication

There are 3 components to the debug process:

1. Client - the software that exposes the debugger UI, e.g. VSCode
1. DAP Server - the broken between the client and debugee, e.g. `ansibug`
1. Debugee - the software to be debugged, e.g. `ansible-playbook`

The communication between the client and the DAP Server is done through process stdio.
The client will spawn the DAP server and send messages through the stdin pipe and receive responses back on the stdout pipe.
Each of these messages is in the DAP protocol format.

The communication between the DAP Server and Debugee depends on the launch type chosen.
In the `Launch` and `Listen` scenarios the DAP server creates a socket to bind to and waits for the debugee to connect to.
In the `Attach by *` scenarios the DAP server will communicate to the debugee using sockets.
