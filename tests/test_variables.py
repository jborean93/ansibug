# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import pathlib

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
            # FIXME: Sort out how this is templated
            value="new value",
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
            # FIXME: Sort out how this is templated
            value="new value",
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
