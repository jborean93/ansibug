# Ansibug

POC for an Ansible Debug Adapter Protocol Runner debugger.
See the [demo folder](./demo/) for some example DAP clients that have been configured to use `ansibug` for testing.

# Workflow

VSCode will use the [DebugAdapterExecutable](https://vshaxe.github.io/vscode-extern/vscode/DebugAdapterExecutable.html) to launch `python -m ansibug dap`.
This entrypoint will use the stdout and stdin to communicate with VSCode and runs locally.
It expects the following messages as defined in DAP:

+ [InitializeRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Initialize)
  + Contains the capabilities of the VSCode client
  + Responds with the `InitializeResponse` that contains the capabilities of `ansibug`
+ [LaunchRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Launch) or [AttachRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Attach)
  + Contains the VSCode launch.json configuration that is being run
  + The structure is dependent on the VSCode plugin but the following launch modes are defined
    + `Launch`
    + `Attach by PID`
    + `Attach by Socket`
    + `Listen` - maybe not wanted or stretch goal
+ [DisconnectRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Requests_Disconnect)
  + Sent at the end of the debugging session
  + Responds with the `DisconnectResponse`

Any other messages are expected to occur after the debuggee (Ansible) has launched and is connected with the DA server.
The messages are then processed by Ansible and passed through the Debug Adapter server.

The 4 launch modes are details below.

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

The `ansibug` DA server will do the following in response to this message:

+ Bind a new socket on localhost
+ Send a [RunInTerminalRequest](https://microsoft.github.io/debug-adapter-protocol/specification#Reverse_Requests_RunInTerminal)
  + Will request VSCode to spawn `python -m ansibug launch --wait-for-client --connect localhost:1234 ...`
  + Expects a `RunInTerminalResponse` with the process id or shell id of the spawned ansible-playbook process
  + The spawned process will start `ansible-playbook` using the args specified and connect to `localhost:1234`
+ There is now a socket that the DA server and ansible-playbook process can communicate with
  + The DA server will continue to receive messages over stdin but will act as a middle man to `ansible-playbook`

## Attach by PID

Sent by VSCode when the `attach` request with a `processId` is specified.
This request type is used to attach to an existing `ansible-playbook` process locally and debug it.
The target process can be spawned with `python -m ansibug launch --listen localhost:1234 ...` which does all the magic to set up the required plugins for ansibug.
This command starts the `ansible-playbook` process with the required options set so it starts in socket listen mode.

The `ansibug` DA server will do the following in response to this message:

+ Read file `/tmp/ANSIBUG-{pid}` to get the socket addr used.
+ Connect to the socket specified.
+ Relay all subsequent messages to the socket.

_note: `python -m ansibug launch ...` isn't strictly needed, as long as `ansible-playbook` was spawned with the ansibug collection plugins this will work._

## Attach by Socket

Sent by VSCode when the `attach` request with a socket addr is specified.
This request type is used to attach to an existing `ansible-playbook` process on a remote host.
The target process must be spawned by `python -m ansibug launch --listen 0.0.0.0:1234 ...` which does all the magic to set up Ansible with a socket listener.

The `ansibug` DA server will do the following in response to this message:

+ Attemp to connect to the addr specified
+ Relay all subsequent messages to the socket

## Listen

This is hypothetical, not sure if it will be possible.
VSCode will sent this request that is going to wait until an `ansibug` process connects to it.
The `ansible-playbook` process is started through `python -m ansibug launch --connect hostname:1234 ...`.
This spawns the `ansible-playbook` process and have it communicate with the DA server.
The DA server will then relay the subsequent messages exchanged over the socket back to VSCode.

This is essentially the same as `Launch` except it waits until the `ansibug` process is manually started rather than starting it itself.

# Communication

There are 3 components to the debug process:

1. Client - the software that exposes the debugger UI, e.g. VSCode
1. DA Server - the broker between the client and debugee, e.g. `ansibug`
1. Debuggee - the software to be debugged, e.g. `ansible-playbook`

The communication between the client and the DA Server is done through process stdio.
The client will spawn the DA server and send messages through the stdin pipe and receive responses back on the stdout pipe.
Each of these messages is in the DA protocol format.

The communication between the DA Server and Debuggee is done through a temporary socket.
The server and client ends depend on the launch mode used:

* Launch and Listen will have the DA server act as the server socket
* Attach by PID and by Socket will have the Debuggee act as the server socket

The messages exchanged by the DA Server and Debuggee use Python's Pickle library to avoid having to implement it's own serialization logic.
The messages will be the same DAP dataclasses as defined in `ansibug.dap.*`.

## TLS Certificates

While not fully tested the current code is written in a way that it should be trivial to support TLS wrapped sockets so the client can verify the server's identity as well as encrypt the data exchanged between the two parties.
For this to work the server certificates need to be generated, the following can be used to generate some for testing:

```bash
openssl ecparam \
    -name secp384r1 \
    -genkey \
    -noout \
    -out ansibug-ca.key

openssl req \
    -new \
    -x509 \
    -out ansibug-ca.pem \
    -key ansibug-ca.key \
    -days 365 \
    -subj "/CN=Ansibug CA"

openssl ecparam \
    -name secp384r1 \
    -genkey \
    -noout \
    -out ansibug.key

openssl req \
    -new \
    -x509 \
    -out ansibug.pem \
    -key ansibug.key \
    -days 365 \
    -subj "/CN=ansibug" \
    -addext "subjectAltName = DNS:localhost,IP:127.0.0.1"  \
    -CA ansibug-ca.pem \
    -CAkey ansibug-ca.key

rm ansibug-ca.key
cat ansibug.key >> ansibug.pem
rm ansibug.key
```

_Note: This not a secure way to store these keys and should only be used for testing purposes._

When starting the DAP server (in the VSCode extension) it should now be started with:

```bash
python -m ansibug \
    dap \
    --tls-cert ansibug.pem
```

Then when the client runs the `launch` configuration it must set the `useTLS` launch property/argument to `True`.
It should also set `tlsVerification` property/argument to `ansibug-ca.pem` unless the host already trusts the signer of the server certificate.

# Debugging Details

When debugging a playbook the debugger treats each host as a separate thread and a breakpoint on a task will break on all the hosts that run that task.
For example the following play will run on `host1`, and `host2` and the breakpoint on the `ping` task will fire for both hosts.

```yaml
- hosts: host1,host2
  task:
  - ping:  # Breakpoint here
```

Running a play with lots of hosts will cause a break a lot of times which could be annoying.
Luckily breakpoints support conditional expressions so it can be set with `inventory_hostname == 'host1'` to restrict when a breakpoint will fire.
The expressions aren't limited to checking `inventory_hostname`, they can be any valid Jinja2 expression that you would typically use in a task's `when:` value.

When a breakpoint is hist the Call Stack will display each host as their own thread with the current host that hit the breakpoint with the call stack expanded.
This call stack contains the current task location as well as the parent include if it was included from anything.
The stack's variables are split into 4 types:

* Module Options - Options set on the module, for example `file: path=/tmp state=directory` will contain `path: /tmp` and `state: directory`
* Task Variables - A snapshot of the variables the task has access to
* Host Variables - A snapshot of the variables of the current host in question, this is similar to `{{ hostvars[inventory_hostname }}`
* Global Variables - A snapshot of all the variables of the play, this is similar to `{{ vars }}`

As module options are templated in the worker process, the debuggee does a basic attempt to template the raw options on the task when displaying them.
The output for module options may fail to template if it's referencing a variable in a loop, like `{{ item }}`.
Setting a variable in the `Task Variables` scope will limit the setting to just the task for the host and nothing else.
Setting a variable in the `Host Variables` or `Global Variables` could affect other tasks or fail if they are meant to be read only.
Currently set variables only supports setting a string value and no expressions.

The actions available to the client when a breakpoint is hit are the following:

* Continue - Will resume execution until the next breakpoint is hit
* Next/Step Over - Will run the task and stop when the next task for the host is reached
* Step In - If stopped on an `include_*` task, will run the include and break on the first task in that include, otherwise acts like `Next/Step Over`
* Step Out - Will continue to run the tasks in the current `include_*` set ignoring and remaining breakpoints. Will break on the next subsequent task outside the include

Because breakpoints are run per host, each of these actions are associated with a host.
Stepping over a task for one host will not affect the breakpoints for other hosts.

# Known Problems

There are a few known problems that cannot be fixed without extra work being done in Ansible itself.
These problems are:

## Static Imports

Because static imports are resolved when the Playbook is processed they cannot have breakpoints set on them.
Attempting to set a breakpoint on one of these entries will result in the breakpoint being set for the previous task found.
This is because the set of tasks when received by the strategy or debug callback have already had the imported tasks get resolved and no stub remains to denote where an import happened.
The resolution happens before any custom plugin can inspect this data which is why the changes need to happen in Ansible.

Known tasks that use static imports:

* `import_tasks`
* `import_role`
* `import_playbook`
* `roles` on a play

A hypothetical fix would be to have these tasks appear as a no-op in the play blocks so they are seen by the strategy plugin.
This would allow the debuggee to detect both where the task is in a file as well as block the play when it's hit.
One thing to keep in mind is being able to detect when the last imported task has run for an import to preserve the correct stackframe information.

## Blocks

While it might be possible to set a breakpoint on the start of a block it is more difficult to set a block to the start of the `rescue` or `always` section.
The `rescue` and `always` section aren't designated with a line in the `Block` object making it impossible to determine where the previous task ends and it starts (see Breakpoint Validation).

For example:

```yaml
- block:  # Cannot set a breakpoint here
  - ping:

  rescue:  # Cannot set a breakpoint here
  - ping:

  always:  # Cannot set a breakpoint here
  - ping:
```

Because blocks are essentially a container for tasks and the inner tasks themselves can still be debugged, the simplest option is to not support them at all and direct people to set a breakpoint on the tasks that are inside it instead which work just fine.

## Breakpoint Validation

The logic to validate whether a breakpoint is valid has a few problems that could confuse users.
When a breakpoint is set, the client sends the file path and line that the breakpoint was set at the the debuggee is meant to validate these details.
If the breakpoint is invalid the debuggee can provide a hint as to why it isn't invalid, and if it's valid the debuggee can set a corrected location.
Using the example below:

```yaml
- name: ping task
  ping:  # Breakpoint set here
```

The breakpoint is set on the `ping:` line and when debuggee validates the breakpoint it will send a correction telling the client the breakpoint is for the `- name: ping task` line.
Achieving this in the debuggee is difficult as it only has access to the tasks that have been processed for the playbook.
These tasks contain the file and line they start with but do not have the end range making it near impossible to accurately tell when a task definition ends.
The current workaround is to treat the task start line and all subsequent lines until the next definition as part of that task.
Based on the example below, lines 1-3 will set a breakpoint for `task 1` on line 1, whereas 4+ will set a breakpoint for `task 2`.

```yaml
- name: task 1
  ping:

- name: task 2
  ping:
```

There are some problems with this approach

### Static imports are not preserved in the task block

Because the static imports are pre-processed before reaching the stategy or debug callback plugins they do not appear in the task blocks.
The playbook task block is used to validate breakpoints and without the parsed yaml metadata the validator cannot detect these entries.
The result of this problem is that the import task and subsequent lines are treated as part of a previous task (if present).
For example:

```yaml
- name: task 1
  ping:

- import_tasks: sub_tasks.yml

- ping:  # Any line before this is a breakpoint for task 1
```

### The always and rescue sections of a block do not contain line metadata

As mentioned in Blocks, the `always` and `rescue` sections are not present in the task block and thus the line information is lost.
This means that the `always` and `rescue` sections are treated as part of the preceding task if present.
The `block` part can be detected and the validator will return an invalidated breakpoint and a msg stating a breakpoint cannot be set on the block.

### JSON Support

While untested I think JSON can be supported in basic scenarios but might be tricky if dealing with compressed json without newlines.
I'm not sure if this is worth the effort to implement.

### Includes Runs On Demand

Because of the nature of include tasks, these are run at runtime rather than before the playbook starts.
This means that the breakpoint validation cannot parse all the files at the start and may have to do it for any new files/tasks that appear during the run.
This isn't too bad as DAP allows breakpoints to be updated during a run allowing the client to validate the breakpoints based on new information that has been processed.

Overall I'm not too happy with the breakpoint validation logic and propbably needs a better implementation.
For now things sortoff works but it might just be better to do an initial pass of the provided playbooks by parsing the yaml file manually and doing it's own logic to map out where breakpoints can be set.

## Loops

Loops are implemented on the forked worker and not the strategy iterator.
This means a breakpoint on a task with a loop will only fire before the task starts rather than during each iteration.
This hasn't been looked at further but will most likely cause problems, especially when combined with `include_tasks`.
Will have to look at this further.

## Deadlocks

While I've strived to remove any deadlocks that might cause a deadlock when debugging a task there are still some that exist.
There's not much that can be done about this expect to try and write a bit more defensive code to ensure a failure is recoverable and the Ansible playbook can continue to run on a failure.
In the event of a deadlock, the simplest solution is to kill the `ansible-playbook` process that was spawned.

# TODO

While this is a POC there are a few outstanding things I am hoping to do before actually releasing this as a plugin.

* Cleanup the code and remove the duplication
* Sort out handler and `meta` task logic
* Have the strategy inject itself over the existing `linear`, `free`, something else if possible, currently only `linear` works
