# Changelog

## 0.4.0 - TBD

+ Added support for Ansible 2.21, 2.22, and Python 3.15
+ Catch `AnsibleUndefinedVariable` when enumerating templated host variables using an undefined variable, the raw templated string will be returned
+ Passthrough the raw `ansible-config` output on a failure to help the caller figure out why it failed
+ Return a descriptive launch error when `ansible-playbook` exits before connecting to the debug adapter, previously a confusing `NotImplementedError` for `DisconnectRequest` was shown - https://github.com/jborean93/ansibug/issues/50
+ Fix `ansible-playbook` hanging on exit when it fails after connecting to the debug adapter
+ Run the launch script through `/bin/sh` so it works when the temporary directory is mounted with `noexec` - https://github.com/jborean93/ansibug/issues/47
+ Fix race condition where the `continue`, `next`, `stepIn`, and `stepOut` responses could be sent after events emitted by the resumed threads
+ Fix launch failure when `ANSIBLE_DEBUG` is enabled, the debug output broke the parsing of the Ansible config
+ Return an error response for unknown requests, like `pause`, and for requests sent before a playbook is launched or attached instead of ending the debug adapter
+ Fix the debug adapter using 100% CPU when the client closes stdin without sending a `disconnect` request
+ Return a launch error when the client fails the `runInTerminal` request instead of ending the debug adapter
+ Fix race condition where messages from the client and the `ansible-playbook` process could be interleaved when written to the client
+ No longer fail when the client message sequence numbers are not contiguous
+ Fix `ansible-playbook` hanging when it fails to connect to the debug adapter, a warning is now shown and the playbook runs without the debugger
+ Fix `ansible-playbook` hanging when the client disconnects before sending `configurationDone`
+ Fix only the first playbook being debuggable when running multiple playbooks with `python -m ansibug listen`
+ Fix duplicate log entries when running multiple playbooks with a log file
+ Fix step over on the last task of an include continuing instead of stopping on the next task
+ Fix step over after stopping on an exception continuing instead of stopping on the next task
+ Fix stale stack frames shown after leaving multiple includes at once or with `include_tasks` that use `apply` or contain a `block`
+ Fix the `Uncaught Failures` exception breakpoint not stopping on a failure in a `rescue` or `always` section of a block
+ Fix race conditions between the client setting breakpoints and Ansible loading new files that could fail the strategy or leave a breakpoint unverified
+ Fix race condition when the client requests the threads while hosts are being added or removed
+ Ignore `continue` and step requests for a thread that has already exited

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
