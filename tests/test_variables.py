# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


def test_playbook_get_set_variable(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: all
  gather_facts: false
  vars:
    foo: bar
  tasks:
  - name: ping test
    ping:
      data: '{{ foo }}'
    register: ping_res

  - name: set fact with overriden option
    set_fact:
      set_var: '{{ fake_var }}'

  - name: check result of previous task
    debug:
      var: set_var
"""
    )

    inventory = tmp_path / "inventory.ini"
    inventory.write_text(
        r"""
host1 ansible_host=127.0.0.1 ansible_connection=local ansible_python_interpreter={{ansible_playbook_python}} my_var=foo
host2 ansible_host=127.0.0.1 ansible_connection=local ansible_python_interpreter={{ansible_playbook_python}} my_var=bar
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path, playbook_args=["-i", "inventory.ini"])

    resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7, 13, 17],
            breakpoints=[dap.SourceBreakpoint(line=7), dap.SourceBreakpoint(line=13), dap.SourceBreakpoint(line=17)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host1_tid = thread_event.thread_id

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [resp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping test"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    assert len(scope_resp.scopes) == 4
    assert scope_resp.scopes[0].name == "Module Options"
    assert scope_resp.scopes[1].name == "Task Variables"
    assert scope_resp.scopes[2].name == "Host Variables"
    assert scope_resp.scopes[3].name == "Global Variables"

    mod_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[0].variables_reference),
        dap.VariablesResponse,
    )
    assert len(mod_vars.variables) == 1
    assert mod_vars.variables[0].name == "data"
    assert mod_vars.variables[0].value == "'bar'"

    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    for v in task_vars.variables:
        if v.name == "inventory_hostname":
            assert v.value == "'host1'"
            break
    else:
        raise Exception("Failed to find inventory_hostname in task vars")

    host_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[2].variables_reference),
        dap.VariablesResponse,
    )
    for v in host_vars.variables:
        if v.name == "my_var":
            assert v.value == "'foo'"
            break
    else:
        raise Exception("Failed to find my_var in host vars")

    global_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[3].variables_reference),
        dap.VariablesResponse,
    )
    for v in global_vars.variables:
        if v.name == "hostvars":
            hostvar_id = v.variables_reference
            assert v.value.startswith("{")
            assert v.value.endswith("}")
            break
    else:
        raise Exception("Failed to find hostvars in global vars")

    global_host_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=hostvar_id),
        dap.VariablesResponse,
    )
    assert "host1" in [v.name for v in global_host_vars.variables]
    assert "host2" in [v.name for v in global_host_vars.variables]

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [resp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping test"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    assert len(scope_resp.scopes) == 4
    assert scope_resp.scopes[0].name == "Module Options"
    assert scope_resp.scopes[1].name == "Task Variables"
    assert scope_resp.scopes[2].name == "Host Variables"
    assert scope_resp.scopes[3].name == "Global Variables"

    mod_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[0].variables_reference),
        dap.VariablesResponse,
    )
    assert len(mod_vars.variables) == 1
    assert mod_vars.variables[0].name == "data"
    assert mod_vars.variables[0].value == "'bar'"

    dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="data",
            value="'override'",
        ),
        dap.SetVariableResponse,
    )

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [resp.breakpoints[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "set fact with overriden option"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="set_var",
            value="'new value'",
        ),
        dap.SetVariableResponse,
    )

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [resp.breakpoints[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "set fact with overriden option"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="set_var",
            value="'new value'",
        ),
        dap.SetVariableResponse,
    )

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [resp.breakpoints[2].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "check result of previous task"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    for v in task_vars.variables:
        if v.name == "set_var":
            assert v.value == "'new value'"
            break
    else:
        raise Exception("Failed to find set_var in host vars")

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [resp.breakpoints[2].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "check result of previous task"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    for v in task_vars.variables:
        if v.name == "set_var":
            assert v.value == "'new value'"
            break
    else:
        raise Exception("Failed to find set_var in host vars")

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.thread_id == host1_tid
    assert thread_event.reason == "exited"

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.thread_id == host2_tid
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_get_variable_critical_failure(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - debug:
      msg: Placeholder 1
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path)

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=5)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    # Sending a bad variable reference should test out a failure in the debugger.
    err = dap_client.send(dap.VariablesRequest(variables_reference=666), dap.ErrorResponse)
    assert isinstance(err, dap.ErrorResponse)
    assert err.message
    assert "KeyError: 666" in err.message

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_playbook_set_task_and_hostvars(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  vars:
    foo: bar
  tasks:
  - set_fact:
      my_test: '{{ foo }}'

  - debug:
      msg: Placeholder
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path)

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7],
            breakpoints=[dap.SourceBreakpoint(line=7)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    # Check that both the task vars and host vars see foo
    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    for v in task_vars.variables:
        if v.name == "foo":
            assert v.value == "'bar'"
            break
    else:
        raise Exception("Failed to find foo in task vars")
    host_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[2].variables_reference),
        dap.VariablesResponse,
    )
    for v in host_vars.variables:
        if v.name == "foo":
            assert v.value == "'bar'"
            break
    else:
        raise Exception("Failed to find foo in host vars")

    # Setting a task var will set it only for the task whereas setting a
    # hostvar will set it for the host beyond the task
    dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[1].variables_reference,
            name="foo",
            value="'value 1'",
        ),
        dap.SetVariableResponse,
    )
    dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[2].variables_reference,
            name="foo",
            value="'value 2'",
        ),
        dap.SetVariableResponse,
    )

    dap_client.send(dap.StepInRequest(thread_id=localhost_tid), dap.StepInResponse)
    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    to_check = {"foo", "my_test"}
    for v in task_vars.variables:
        # The foo value will be set to the hostvars value
        if v.name == "foo":
            to_check.remove("foo")
            assert v.value == "'value 2'"
            assert v.type == "str"

        # This will be the saved value from when the taskvars changed
        elif v.name == "my_test":
            to_check.remove("my_test")
            assert v.value == "'value 1'"
            assert v.type == "str"

        if not to_check:
            break

    assert not to_check

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_playbook_set_variable_types(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  vars:
    foo: bar
  tasks:
  - name: set fact
    set_fact:
      my_bool: abc
      my_dict: abc
      my_int: abc
      my_list: abc
      my_str: abc
      my_var: abc

  - debug:
      msg: Placeholder
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path)

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7],
            breakpoints=[dap.SourceBreakpoint(line=7)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    bool_resp = dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="my_bool",
            value="True",
        ),
        dap.SetVariableResponse,
    )
    assert bool_resp.value == "True"
    assert bool_resp.type == "bool"

    dict_resp = dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="my_dict",
            value='{"foo": "bar", "int": 1}',
        ),
        dap.SetVariableResponse,
    )
    assert dict_resp.value == repr({"foo": "bar", "int": 1})
    assert dict_resp.type == "dict"

    int_resp = dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="my_int",
            value="1",
        ),
        dap.SetVariableResponse,
    )
    assert int_resp.value == "1"
    assert int_resp.type == "int"

    list_resp = dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="my_list",
            value="[1, '2', true, false]",
        ),
        dap.SetVariableResponse,
    )
    assert list_resp.value == repr([1, "2", True, False])
    assert list_resp.type == "list"

    str_resp = dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="my_str",
            value='"string value"',
        ),
        dap.SetVariableResponse,
    )
    assert str_resp.value == "'string value'"
    assert str_resp.type == "str"

    var_resp = dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[0].variables_reference,
            name="my_var",
            value="foo",
        ),
        dap.SetVariableResponse,
    )
    assert var_resp.value == "'bar'"
    assert var_resp.type == "AnsibleUnicode"

    dap_client.send(dap.StepInRequest(thread_id=localhost_tid), dap.StepInResponse)
    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    to_check = {"my_bool", "my_dict", "my_int", "my_list", "my_str", "my_var"}
    for v in task_vars.variables:
        if v.name == "my_bool":
            to_check.remove("my_bool")
            assert v.value == "True"
            assert v.type == "bool"

        elif v.name == "my_dict":
            to_check.remove("my_dict")
            assert v.value == repr({"foo": "bar", "int": 1})
            assert v.type == "dict"

        elif v.name == "my_int":
            to_check.remove("my_int")
            assert v.value == "1"
            assert v.type == "int"

        elif v.name == "my_list":
            to_check.remove("my_list")
            assert v.value == repr([1, "2", True, False])
            assert v.type == "list"

        elif v.name == "my_str":
            to_check.remove("my_str")
            assert v.value == "'string value'"
            assert v.type == "str"

        elif v.name == "my_var":
            to_check.remove("my_var")
            assert v.value == "'bar'"
            assert v.type == "AnsibleUnicode"

        if not to_check:
            break

    assert not to_check

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


@pytest.mark.parametrize("set_native", [False, True])
def test_playbook_set_list_and_dict_value(
    set_native: bool,
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  vars:
    my_list:
    - 1
    - 2
    my_dict:
      foo: bar
      other: old value
  tasks:
  - set_fact:
      final_var:
        list: '{{ my_list }}'
        dict: '{{ my_dict }}'

  - debug:
      msg: Placeholder
"""
    )

    new_env = {}
    if set_native:
        new_env["ANSIBLE_JINJA2_NATIVE"] = "true"
    proc = dap_client.launch("main.yml", playbook_dir=tmp_path, launch_options={"env": new_env})

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[12],
            breakpoints=[dap.SourceBreakpoint(line=12)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    var_resp = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    list_var_id = None
    dict_var_id = None
    for v in var_resp.variables:
        if v.name == "my_list":
            list_var_id = v.variables_reference
        elif v.name == "my_dict":
            dict_var_id = v.variables_reference

        if list_var_id is not None and dict_var_id is not None:
            break
    else:
        raise Exception("Failed to find my_list and my_dict variable id")

    list_resp = dap_client.send(
        dap.SetVariableRequest(
            variables_reference=list_var_id,
            name="1",
            value="3",
        ),
        dap.SetVariableResponse,
    )
    assert list_resp.value == "3"
    assert list_resp.type == "int"

    dict_resp = dap_client.send(
        dap.SetVariableRequest(
            variables_reference=dict_var_id,
            name="other",
            value="'new value'",
        ),
        dap.SetVariableResponse,
    )
    assert dict_resp.value == "'new value'"
    assert dict_resp.type == "str"

    dap_client.send(dap.StepInRequest(thread_id=localhost_tid), dap.StepInResponse)
    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    for v in task_vars.variables:
        if v.name != "final_var":
            continue

        final_var = dap_client.send(
            dap.VariablesRequest(variables_reference=v.variables_reference),
            dap.VariablesResponse,
        )
        assert len(final_var.variables) == 2
        for final_v in final_var.variables:
            if final_v.name == "list":
                assert final_v.value == repr([1, 3])
                assert final_v.type == "list"

                list_values = dap_client.send(
                    dap.VariablesRequest(variables_reference=final_v.variables_reference),
                    dap.VariablesResponse,
                )
                assert len(list_values.variables) == 2
                assert list_values.variables[0].name == "0"
                assert list_values.variables[0].value == "1"
                assert list_values.variables[1].name == "1"
                assert list_values.variables[1].value == "3"

            else:
                assert final_v.value == repr({"foo": "bar", "other": "new value"})
                assert final_v.type == "dict"

                dict_values = dap_client.send(
                    dap.VariablesRequest(variables_reference=final_v.variables_reference),
                    dap.VariablesResponse,
                )
                assert len(dict_values.variables) == 2
                assert dict_values.variables[0].name == "foo"
                assert dict_values.variables[0].value == "'bar'"
                assert dict_values.variables[1].name == "other"
                assert dict_values.variables[1].value == "'new value'"

        break
    else:
        raise Exception("Failed to find final_var for test")

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_playbook_eval(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  vars:
    foo: bar
  tasks:
  - debug:
      msg: Placeholder
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path)

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7],
            breakpoints=[dap.SourceBreakpoint(line=7)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "foo",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == "'bar'"
    assert eval_resp.type == "AnsibleUnicode"

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!template foo",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == "'bar'"
    assert eval_resp.type == "AnsibleUnicode"

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!t foo",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == "'bar'"
    assert eval_resp.type == "AnsibleUnicode"

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "foo",
            frame_id=st_resp.stack_frames[0].id,
            context="watch",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == "'bar'"
    assert eval_resp.type == "AnsibleUnicode"

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "foo",
            frame_id=st_resp.stack_frames[0].id,
            context="clipboard",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == "'bar'"
    assert eval_resp.type == "AnsibleUnicode"

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "foo",
            frame_id=st_resp.stack_frames[0].id,
            context="variables",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == "'bar'"
    assert eval_resp.type == "AnsibleUnicode"

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "invalid",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == "AnsibleUndefinedVariable: 'invalid' is undefined. 'invalid' is undefined"
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "{{ template_err",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert "template error while templating string" in eval_resp.result
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "not implemented",
            frame_id=st_resp.stack_frames[0].id,
            context="unknown",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == "Evaluation for unknown is not implemented"
    assert eval_resp.type is None

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_eval_repl_set_option(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  vars:
    foo: bar
  tasks:
  - set_fact:
      option_to_be_changed: value

  - debug:
      msg: Placeholder
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path)

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7],
            breakpoints=[dap.SourceBreakpoint(line=7)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!set_option added 'value'",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!set_option 'added_with_single_quote' 'value'",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            '!so "added_with_double_quote" "value with space"',
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!so option_to_be_changed foo",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    def check_vars(variables: list[dap.Variable]) -> None:
        to_check = {"added", "added_with_single_quote", "added_with_double_quote", "option_to_be_changed"}
        for v in variables:
            if v.name == "added":
                to_check.remove("added")
                assert v.value == "'value'"
                assert v.type == "str"

            elif v.name == "added_with_single_quote":
                to_check.remove("added_with_single_quote")
                assert v.value == "'value'"
                assert v.type == "str"

            elif v.name == "added_with_double_quote":
                to_check.remove("added_with_double_quote")
                assert v.value == "'value with space'"
                assert v.type == "str"

            elif v.name == "option_to_be_changed":
                to_check.remove("option_to_be_changed")
                assert v.value == "'bar'"
                assert v.type == "AnsibleUnicode"

            if not to_check:
                break

        assert not to_check

    module_opts = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[0].variables_reference),
        dap.VariablesResponse,
    )
    check_vars(module_opts.variables)

    dap_client.send(dap.StepInRequest(thread_id=localhost_tid), dap.StepInResponse)
    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    check_vars(task_vars.variables)

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_eval_repl_remove_option(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  vars:
    foo: bar
  tasks:
  - set_fact:
      option1: value
      to_be_removed1: value
      to_be_removed2: value

  - debug:
      msg: Placeholder
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path)

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7],
            breakpoints=[dap.SourceBreakpoint(line=7)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!remove_option to_be_removed1",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!ro 'to_be_removed2'",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!ro option_not_present_no_failure",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    module_opts = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[0].variables_reference),
        dap.VariablesResponse,
    )
    assert len(module_opts.variables) == 1

    dap_client.send(dap.StepInRequest(thread_id=localhost_tid), dap.StepInResponse)
    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    to_find = {"to_be_removed1", "to_be_removed2"}
    for v in task_vars.variables:
        if v.name in to_find:
            to_find.remove(v.name)

        if not to_find:
            break

    assert len(to_find) == 2

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_eval_repl_set_hostvar_option(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  vars:
    foo: bar
  tasks:
  - set_fact:
      my_var: '{{ unset_var }}'

  - debug:
      msg: Placeholder 2
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path)

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7],
            breakpoints=[dap.SourceBreakpoint(line=7)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    host_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[2].variables_reference),
        dap.VariablesResponse,
    )
    new_var_found = False
    for v in host_vars.variables:
        if v.name == "foo":
            assert v.value == "'bar'"

        elif v.name == "new_var":
            new_var_found = True

    assert not new_var_found

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!set_hostvar foo 'value 1'",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!sh new_var 'value 2'",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!sh unset_var 'biz'",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result == ""
    assert eval_resp.type is None

    host_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[2].variables_reference),
        dap.VariablesResponse,
    )
    to_find = {"foo", "new_var"}
    for v in host_vars.variables:
        if v.name == "foo":
            to_find.remove("foo")
            assert v.value == "'value 1'"

        elif v.name == "new_var":
            to_find.remove("new_var")
            assert v.value == "'value 2'"

        if not to_find:
            break

    assert not to_find

    dap_client.send(dap.StepInRequest(thread_id=localhost_tid), dap.StepInResponse)
    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    # Ensure the hostvars have persisted to the next task.
    host_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[2].variables_reference),
        dap.VariablesResponse,
    )
    to_find = {"foo", "new_var", "my_var"}
    for v in host_vars.variables:
        if v.name == "foo":
            to_find.remove("foo")
            assert v.value == "'value 1'"

        elif v.name == "new_var":
            to_find.remove("new_var")
            assert v.value == "'value 2'"

        elif v.name == "my_var":
            to_find.remove("my_var")
            assert v.value == "'biz'"

        if not to_find:
            break

    assert not to_find

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_eval_repl_invalid_commands(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - debug:
      msg: Placeholder 1
"""
    )

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path)

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=5)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    dap_client.wait_for_message(dap.StoppedEvent)
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!--help",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result.startswith("usage: ! [-h] ")
    assert "Ansibug debug console repl commands" in eval_resp.result

    eval_resp = dap_client.send(
        dap.EvaluateRequest(
            "!unknown",
            frame_id=st_resp.stack_frames[0].id,
            context="repl",
        ),
        dap.EvaluateResponse,
    )
    assert eval_resp.result.startswith("argument command: invalid choice: 'unknown' (choose from ")

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")
