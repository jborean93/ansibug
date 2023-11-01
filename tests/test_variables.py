# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

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

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host2_tid = thread_event.thread_id

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

            else:
                assert final_v.value == repr({"foo": "bar", "other": "new value"})
                assert final_v.type == "dict"

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
            "not implemted",
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
