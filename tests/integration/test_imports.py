# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

import pytest
from dap_client import DAPClient, DAPErrorResponse

import ansibug.dap as dap


def _assert_stopped(
    dap_client: DAPClient,
    tid: int,
    reason: dap.StoppedReason,
    frames: list[tuple[str, pathlib.Path, int]],
) -> None:
    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == reason
    assert stopped_event.thread_id == tid

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    actual = [(f.name, f.source.path if f.source else None, f.line) for f in st_resp.stack_frames]
    assert actual == [(name, str(path), line) for name, path, line in frames]


def test_import_tasks(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: import tasks
    import_tasks: tasks.yml

  - name: ping 3
    ping:
"""
    )

    tasks = tmp_path / "tasks.yml"
    tasks.write_text("- name: ping 2\n  ping:\n\n- name: ping 2a\n  ping:")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    play_bp = dap_client.set_breakpoints(playbook, 8)
    assert play_bp[0].verified
    assert play_bp[0].line == 8
    assert play_bp[0].end_line == 10

    tid = dap_client.configuration_done()

    import_frame = ("import tasks", playbook, 8)
    _assert_stopped(dap_client, tid, dap.StoppedReason.BREAKPOINT, [import_frame])

    dap_client.send(dap.StepInRequest(thread_id=tid), dap.StepInResponse)
    _assert_stopped(dap_client, tid, dap.StoppedReason.STEP, [("ping 2", tasks, 1), import_frame])

    dap_client.send(dap.NextRequest(thread_id=tid), dap.NextResponse)
    _assert_stopped(dap_client, tid, dap.StoppedReason.STEP, [("ping 2a", tasks, 4), import_frame])

    dap_client.send(dap.StepOutRequest(thread_id=tid), dap.StepOutResponse)
    _assert_stopped(dap_client, tid, dap.StoppedReason.STEP, [("ping 3", playbook, 11)])

    dap_client.continue_to_end(proc, tid)


def test_import_role(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: import role
    import_role:
      name: my_role

  - name: ping 3
    ping:
"""
    )

    role_tasks = tmp_path / "roles" / "my_role" / "tasks"
    role_tasks.mkdir(parents=True)
    tasks = role_tasks / "main.yml"
    tasks.write_text("- name: ping 2\n  ping:")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    tasks_bp = dap_client.set_breakpoints(tasks, 1)
    assert tasks_bp[0].verified

    tid = dap_client.configuration_done()

    import_frame = ("import role", playbook, 5)
    _assert_stopped(dap_client, tid, dap.StoppedReason.BREAKPOINT, [("my_role : ping 2", tasks, 1), import_frame])

    dap_client.send(dap.StepOutRequest(thread_id=tid), dap.StepOutResponse)
    _assert_stopped(dap_client, tid, dap.StoppedReason.STEP, [("ping 3", playbook, 9)])

    dap_client.continue_to_end(proc, tid)


def test_step_over_import(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: import tasks
    import_tasks: tasks.yml

  - name: ping 3
    ping:
"""
    )

    tasks = tmp_path / "tasks.yml"
    tasks.write_text("- name: ping 2\n  ping:")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.set_breakpoints(playbook, 5)
    tid = dap_client.configuration_done()

    _assert_stopped(dap_client, tid, dap.StoppedReason.BREAKPOINT, [("ping 1", playbook, 5)])

    dap_client.send(dap.NextRequest(thread_id=tid), dap.NextResponse)
    _assert_stopped(dap_client, tid, dap.StoppedReason.STEP, [("import tasks", playbook, 8)])

    dap_client.send(dap.NextRequest(thread_id=tid), dap.NextResponse)
    _assert_stopped(dap_client, tid, dap.StoppedReason.STEP, [("ping 3", playbook, 11)])

    dap_client.continue_to_end(proc, tid)


def test_import_options_read_only(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: import tasks
    import_tasks: tasks.yml
"""
    )

    tasks = tmp_path / "tasks.yml"
    tasks.write_text("- name: ping 1\n  ping:")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.set_breakpoints(playbook, 5)
    tid = dap_client.configuration_done()
    dap_client.wait_for_message(dap.StoppedEvent)

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    frame_id = st_resp.stack_frames[0].id
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=frame_id), dap.ScopesResponse)
    options_ref = scope_resp.scopes[0].variables_reference

    with pytest.raises(DAPErrorResponse, match="module options of an import_\\* task cannot be changed"):
        dap_client.send(
            dap.SetVariableRequest(variables_reference=options_ref, name="_raw_params", value="'other.yml'"),
            dap.SetVariableResponse,
        )

    for expression in ["!so _raw_params 'other.yml'", "!so _raw_params omit", "!ro _raw_params"]:
        resp = dap_client.send(
            dap.EvaluateRequest(expression, frame_id=frame_id, context="repl"),
            dap.EvaluateResponse,
        )
        assert "module options of an import_* task cannot be changed" in resp.result

    # Host vars can still be changed.
    resp = dap_client.send(
        dap.EvaluateRequest("!sh my_var 'value'", frame_id=frame_id, context="repl"),
        dap.EvaluateResponse,
    )
    assert "cannot be changed" not in resp.result

    opts_resp = dap_client.send(dap.VariablesRequest(variables_reference=options_ref), dap.VariablesResponse)
    assert [(v.name, v.value) for v in opts_resp.variables] == [("_raw_params", "'tasks.yml'")]

    dap_client.continue_to_end(proc, tid)
