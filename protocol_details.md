# Debug Adapter Protocol
The [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/) (DAP) is the glue that brings all this together.
It is a protocol that defines a common set of messages needed for clients to debug with a programming language without having to reimplement the exchange themselves.
In this case `ansibug` implements DAP and acts as a debug adapter and debuggee component for DAP clients to interact with.
This document will go through more details on how `ansibug` works and how it fits into the landscape.

With DAP there are three actors involves in the process:

+ Client
+ Debug Adapter
+ Debuggee

The client is the front end that displays all the visual elements for the debugger, in this case it will be programs like Visual Studio Code.
It is also in charge of starting the debug adapter, potentially the debuggee, and creating the various request messages needed to drive the DAP.

The debug adapter is the first component of DAP that `ansibug` is involved in.
It is started by the client as part of a debug event and essentially is the actor in the middle that allows the communication between the client and debuggee.
For `ansibug`, the debug adapter is included as part of the `ansibug` Python library and uses stdio communication with the client to exchange the messages.
It can be started manually by running `python -m ansibug dap` and communicating over `stdout` and `stdin`.

The debuggee is the final actor in the DAP exchange.
It is the program that is being debugged which in `ansibug's` case is the `ansible-playbook` process.
It is in charge of doing things like validating breakpoints, emitting debug events, and handling the interaction of the debug requests with Ansible itself.
The debuggee components are implemented as a custom `callback` and `strategy` plugin in Ansible that hooks into the various events in Ansible needed to debug a playbook.
By default is uses a Unix Domain Socket (UDS) to communicate with the debug adapter but it can be configured to use a TCP socket if cross host debugging is desired.

A more in depth overview of DAP can be found on their [Overview page](https://microsoft.github.io/debug-adapter-protocol/overview).

# Message Workflow
When the debug adapter is started by client it will send these two messages first:

+ [Initialize Request](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Initialize)
  + Contains the capabilities of the VSCode client
  + Adapter responds with the `Initialize Response` that contains the capabilities of `ansibug`
+ [Launch Request](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Launch) or [Attach Request](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Attach)
  + This contains the information inside the `launch.json`
  + The arguments is dependent of the request type

If a `Launch Request` was sent the debug adapter will reply with a [RunInTerminal Request](https://microsoft.github.io/debug-adapter-protocol/specification#Reverse_Requests_RunInTerminal).
This request contains the command the client should run in its terminal alongside other details like the working directory and environment variables.
Once the client spawns the process it'll reply with a `RunInTerminal Response` and the debug adapter will wait until the `ansible-playbook` process has connected to the UDS it has started.
Once connected the debug adapter returns a `Launch Response` to let the client know the launch was successful.

If an `Attach Request` was sent the debug adapter will attempt to connect to the already existing `ansible-playbook` process detailed in the request.
Once successful it will respond to the client with an `Attach Response`.

From here all requests from the client provided to the debug adapter are sent to the debuggee through the socket.
Any response or event from the debuggee to the debug adapter will also be passed through to the client.
The only exception to this rule is a [Disconnect Request](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Disconnect) which tells the debug adapter to disconnect from the debuggee.

The `ansible-playbook` process that was launched or attached to is configured to send the [Initialized Event](https://microsoft.github.io/debug-adapter-protocol/specification#Events_Initialized) to indicate it is ready to receive the breakpoint information.
Once the event was received the client will send through all the breakpoint information through a [SetBreakpoints Request](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_SetBreakpoints) for each file.
Once all breakpoints have been sent the client will send a [ConfigurationDone Request](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_ConfigurationDone) to let the `ansible-playbook` know to start running as normal.

As the strategy plugin loops through the tasks needed it will check if a breakpoint has been set for a task and stop if needed with a [Stopped Event](https://microsoft.github.io/debug-adapter-protocol/specification#Events_Stopped).
During this step, information like threads, stack frames, scopes, variables are all exchanged when requested by the client.
This will continue until the `ansible-playbook` process has ended and it closes the socket between the debuggee and debug adapter.
The debug adapter will then send a [Terminated Event](https://microsoft.github.io/debug-adapter-protocol/specification#Events_Terminated) to the client to indicate it is finished.
