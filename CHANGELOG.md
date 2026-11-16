# Changelog

## 0.4.0 - TBD

### Features

+ Added support for Ansible 2.21, 2.22, and Python 3.15
+ Breakpoints
  + Added logpoints, a breakpoint that writes a message to the debug console instead of stopping
    + The message is templated, for example `{{ inventory_hostname }}: installing {{ packages | length }} packages`
  + Added hit conditions to line and function breakpoints to only stop on certain hits
    + The condition is one of the operators `==`, `>`, `>=`, `<`, `<=`, or `%` followed by a number, a number by itself is the same as `==`
    + For example `3` stops on the 3rd hit, `>=3` on every hit from the 3rd, and `%3` on every 3rd hit
    + Each host reaching the task is a hit
  + Added function breakpoints to stop on tasks by module or task name
    + The name is a glob matched against the module as written, the module it resolved to, and the task name
    + For example `ansible.builtin.package` stops on every `package` task, `*.foo` on `foo` from any collection, and `Install *` on tasks named `Install ...`
    + Wrap a glob character in brackets to match it literally, for example `Restart [*]` only matches a task named `Restart *`
+ Exception breakpoints
  + Added conditions to the `Uncaught Failures`, `Unreachable Hosts`, and `Skipped Tasks` exception breakpoints
    + The condition is an Ansible conditional with the task result available as `result`
    + For example `inventory_hostname == 'db1'` only stops when `db1` fails and `'Permission denied' in result.msg` only stops on that error
  + Added the `exceptionInfo` request so clients like can show the error in the exception widget
    + Some clients, like VSCode already used this info, this is to provide other clients another way to retrieve the exception info
    + The error message and the module traceback, if Ansible captured one, are shown separately

### Changes

+ Launch
  + Passthrough the raw `ansible-config` output on a failure to help the caller figure out why it failed
  + Warn when the launch cannot find the `CALLBACKS_ENABLED` or `COLLECTIONS_PATHS` Ansible config, previously the user's values were silently dropped
  + `ansible-playbook` now shows a warning and runs without the debugger when it cannot connect to the debug adapter, previously it hung
+ Performance
  + Reduce the per task overhead of the debug strategy, the host thread lookup no longer scales with the number of hosts and breakpoint conditions are only templated when a breakpoint matches
  + Only template the `Host Variables` scope when it is expanded, and reuse the scope and child variables when a stack frame is selected again while stopped
  + Show `hostvars` as `HostVars (N hosts)` instead of templating every variable of every host to display it, expand it to see each host
+ Use JSON instead of `pickle` for the internal messages between the debug adapter and `ansible-playbook`, attaching to an untrusted address can no longer run code in the debug adapter process
+ Debug Adapter Protocol
  + Return an error response for unknown requests, like `pause`, and for requests sent before a playbook is launched or attached instead of ending the debug adapter
  + Omit unset optional fields from DAP messages instead of sending `null`, as required by the DAP specification
  + Return a clearer message when evaluating an expression without a stack frame

### Bugfixes

+ Launching and attaching
  + Return a descriptive launch error when `ansible-playbook` exits before connecting to the debug adapter, previously a confusing `NotImplementedError` for `DisconnectRequest` was shown - https://github.com/jborean93/ansibug/issues/50
  + Run the launch script through `/bin/sh` so it works when the temporary directory is mounted with `noexec` - https://github.com/jborean93/ansibug/issues/47
  + Fix launch failure when `ANSIBLE_DEBUG` is enabled, the debug output broke the parsing of the Ansible config
  + Return a launch error when the client fails the `runInTerminal` request instead of ending the debug adapter
  + Fix the launch script running its cleanup twice when interrupted with `Ctrl+C` or `SIGTERM`
  + Fix attach hanging when the target accepts the connection but never responds, the handshake now honours `connectTimeout`
  + Fail with a clear error when `python -m ansibug listen --wrap-tls` or the `use_tls` callback option is set without a TLS server certificate, previously a `TypeError` was raised
+ `ansible-playbook` hangs
  + Fix hanging on exit when it fails after connecting to the debug adapter
  + Fix hanging when it fails to connect to the debug adapter
  + Fix hanging when the client disconnects before sending `configurationDone`
+ Running multiple playbooks with `python -m ansibug listen`
  + Fix only the first playbook being debuggable
  + Fix duplicate log entries when a log file is used
+ Debug adapter process
  + Fix the debug adapter using 100% CPU when the client closes stdin without sending a `disconnect` request
  + No longer fail when the client message sequence numbers are not contiguous
  + Fix race condition where messages from the client and the `ansible-playbook` process could be interleaved when written to the client
  + Fix race condition where the `continue`, `next`, `stepIn`, and `stepOut` responses could be sent after events emitted by the resumed threads
+ The `listen` socket
  + Fix it no longer accepting connections after a client connected and then reset the connection or failed the handshake
  + Drop a client that does not complete the handshake within 10 seconds, previously it blocked the listener and shutdown forever
  + Fix socket connect and accept failing when the process has more than 1024 file descriptors open
+ Stepping and stack frames
  + Fix step over on the last task of an include continuing instead of stopping on the next task
  + Fix step over after stopping on an exception continuing instead of stopping on the next task
  + Fix stale stack frames shown after leaving multiple includes at once or with `include_tasks` that use `apply` or contain a `block`
  + Fix the `stepIn` request `targetId` argument overwriting the `threadId`
  + Ignore `continue` and step requests for a thread that has already exited
  + Fix race condition when the client requests the threads while hosts are being added or removed
+ Breakpoints
  + Fix the `Uncaught Failures` exception breakpoint not stopping on a failure in the `rescue` or `always` section of a block, only a failure in the `block` section is rescued by that block

    ```yaml
    - block:
      - fail: msg=first    # Rescued, does not stop
      rescue:
      - fail: msg=second   # Not rescued, now stops on Uncaught Failures
    ```

  + Fix path mappings matching a partial directory name, a root now has to match whole directory names
    + For example a `remoteRoot` of `/foo` previously also mapped `/foobar/main.yml`, now it only maps paths under `/foo/`
  + Fix race conditions between the client setting breakpoints and Ansible loading new files that could fail the strategy or leave a breakpoint unverified
  + Fix the exception breakpoint details showing the raw `ErrorSummary(...)` value on Ansible 2.20 and newer instead of the formatted error
+ Variables and the debug console
  + Fix `!so` and `!ro` changing the module options of the task for every host, they now only apply to the host of the stopped thread
  + Fix `!so` and `!ro` failing when the client has not requested the scopes of the frame yet
  + Return an error message for a debug console command with unbalanced quotes instead of a critical debuggee exception
  + Catch `AnsibleUndefinedVariable` when enumerating templated host variables using an undefined variable, the raw templated string will be returned
  + No longer expand `bytes` values into a list of integers in the variables view
+ Documentation
  + Fix the `no_wait_for_config_done` callback option documentation describing the opposite behaviour and remove the invalid `debug_addr` default

## 0.3.2 - 2025-11-22

+ Bugfixes to work with internal changes introduced with the upcoming Ansible 2.20 release
+ Added support for Ansible 2.20

## 0.3.1 - 2025-07-08

+ Added support for Ansible 2.19 which introduced Data Tagging

## 0.3.0 - 2025-02-24

+ Added support for restart with a `Launch` configuration, trying to restart an `Attach` configuration will stop the process but fail to re-attach
+ Added `--temp-dir` option for `python -m ansibug dap ...` to control the temporary directory used for storing the Ansible launch script
+ Added exception breakpoints for:
  + `Uncaught Failures` - Fired when an error is raised in Ansible but is not ignored or rescued
  + `Unreachable Hosts` - Fired when a host is marked as unreachable
  + `Skipped Tasks` - Fired when a task is skipped
+ Stop deprecation message about custom strategy plugins introduced in Ansible 2.19

## 0.2.0 - 2024-11-10

+ Officially support Ansible 2.18 and Python 3.13
+ Drop support for Ansible 2.14 and 2.15 now they are end of life

## 0.1.2 - 2024-07-16

+ Fix properly setting `COLLECTIONS_PATHS` for an `ansibug` run when no explicit config value was provided

## 0.1.1 - 2024-07-08

+ Officially support Ansible 2.17
+ Fix support for `include_*` tasks with Ansible 2.17+
+ Fix up `ansible-config dump` parser when a config entry has no name
  + Entries with no `name` key was added in Ansible 2.18

## 0.1.0 - 2023-11-13

Initial release of `ansibug`

This version should be treated as a pre-release, any behavior may change in future versions depending on feedback.
