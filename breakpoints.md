# Breakpoints
Ansibug supports the following types of breakpoints:

+ [Line Breakpoints](#line-breakpoints)
+ [Exception Breakpoints](#exception-breakpoints)
  + Uncaught Failures
  + Unreachable Hosts
  + Skipped Tasks

## Line Breakpoints
For a line breakpoint the first step to debugging a playbook is to place a breakpoint on the task you wish to stop at.

![set_breakpoint](./images/set_breakpoint.gif)

It is also possible to set a condition on the breakpoint so that it is only hit when the condition is tree.
The expression for a condition is treated as a template expression just like a `when` task condition.
For example to have the breakpoint only be hit when running on the host `MYSERVER` set the expression to `inventory_hostname == 'MYSERVER'`.

![set_conditional_breakpoint](./images/set_conditional_breakpoint.gif)

The expression will use the variables that are set at the time the breakpoint is set.
It is important not to use `{{ }}` in the expression as the value is already templated.
If the expression is an invalid template it will be treated as `False` and never be hit.

Part of the validation for breakpoints will update the client on the proper locations.
This will happen when the playbook starts if the task has already been loaded.
Otherwise for tasks dynamically loaded at runtime, with something like `include_tasks`, they will only be validated when they are loaded.

![breakpoint_relocation](./images/breakpoint_relocation.gif)

The breakpoints will always move to the first line of the previous task that is known to the debugger.

### Limitations
The following playbook/tasks entries cannot have a breakpoint set on them.

+ Play roles under `roles`

```yaml
- hosts: localhost
  roles:
  - role1
  - role2
```

+ `import_*` tasks

```yaml
- import_playbook: play.yml

- hosts: localhost
  tasks:
  - import_role:
      name: role1

  - import_tasks:
      file: tasks.yml
```

+ The `block`, `rescue`, and `always` lines in a block

```yaml
- block:  # Cannot set a breakpoint here
  - name: task 1
    ping:

  rescue:  # Will snapback to 'task 1'
  - name: task 2
    ping:

  always:  # Will snapback to 'task 2'
  - name: task 3
    ping:
```

Attempting to set a breakpoint on the `block` will be invalidated when the block is loaded.
Setting it on `rescue` or `always` will count as the previous task and will automatically be changed to the correct line when the block is loaded.

![block_breakpoints](./images/block_breakpoints.gif)

This is a limitation with the current breakpoint validation behavior as these entries are not seen by the debug code.
The only thing it can do is treat it as a line as part of the preceding task.

## Exception Breakpoints
By default `ansibug` will enable the `Uncaught Failures` and `Unreachable Hosts` breakpoint which will trigger when a task has failred or a host was marked as unreachable respectively.
It is also possible to enable the `Skipped Tasks` exception breakpoint which will trigger when a task was skipped based on the `is skipped` test.
Enabled or disabling these types of exception breakpoints is done through the `BREAKPOINTS` pane (typically in the bottom left hand section) of the debugger:

![exception_breakpoints](./images/exception_breakpoints.png)

It is important to note that `Uncaught Failures` will not trigger when:

+ The `ignore_errors: true` directive is set on the task
+ The task is contained within a block with a `rescue` section
+ The task failed due to an unreachable host, this will trigger `Unreachable Hosts` instead

The `Unreachable Hosts` breakpoint will not trigger if the `ignore_unreachable: true` directory is set on the task.

When a breakpoint is hit, the UI will focus on the task that triggered the breakpoint and the variables pane will include a new scope called `Module Results` that contains the results of the task.
You can use this pane to get more information about the task and interest with it in the debug console.

![exception_breakpoints_fired](./images/exception_breakpoints_fired.png)

While the UI will allow you to set the variables in this scope, it will not be persisted when the breakpoint continues.
