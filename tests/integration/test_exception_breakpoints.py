# Copyright (c) 2025 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import shutil

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


def test_break_on_error(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
      data: crash
    register: ping_res
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_error"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "started"
    host_tid = resp.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.EXCEPTION
    assert stopped_event.description == "Task failed"
    assert stopped_event.text
    assert "boom" in stopped_event.text
    assert stopped_event.thread_id == host_tid
    assert stopped_event.hit_breakpoint_ids == []

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping test"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    assert len(scope_resp.scopes) == 5
    assert scope_resp.scopes[0].name == "Module Result"
    assert scope_resp.scopes[1].name == "Module Options"
    assert scope_resp.scopes[2].name == "Task Variables"
    assert scope_resp.scopes[3].name == "Host Variables"
    assert scope_resp.scopes[4].name == "Global Variables"

    mod_res = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[0].variables_reference),
        dap.VariablesResponse,
    )

    to_find = {"failed", "exception", "msg"}
    for v in mod_res.variables:
        if v.name == "failed":
            assert v.value == "True"
            assert v.type == "bool"
            to_find.remove("failed")

        elif v.name == "exception":
            assert v.value
            to_find.remove("exception")

        elif v.name == "msg":
            assert v.value
            to_find.remove("msg")

    assert len(to_find) == 0

    dap_client.send(dap.ContinueRequest(thread_id=host_tid), dap.ContinueResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if (rc := proc.returncode) != 2:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_break_on_error_stop_after(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
      data: crash
    register: ping_res
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_error"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "started"
    host_tid = resp.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.EXCEPTION
    assert stopped_event.description == "Task failed"
    assert stopped_event.thread_id == host_tid
    assert stopped_event.hit_breakpoint_ids == []

    dap_client.send(dap.DisconnectRequest(terminate_debuggee=True), dap.DisconnectResponse)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if (rc := proc.returncode) != 2:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_do_not_break_on_error_ignore_errors(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
      data: crash
    ignore_errors: true
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_error"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "started"

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_do_not_break_on_error_in_rescue(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - block:
    - name: ping test
      ping:
        data: crash

    rescue:
    - debug:
        msg: "Rescue ran"
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_error"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "started"

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")

    assert "Rescue ran" in play_out[0].decode()


def test_do_not_break_on_error_unset(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
      data: crash
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_unreachable"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "started"

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if (rc := proc.returncode) != 2:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_break_on_unreachable(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
    vars:
        ansible_connection: ns.name.broken_connection
"""
    )

    connection_src = (
        pathlib.Path(__file__).parent.parent
        / "data"
        / "ansible_collections"
        / "ns"
        / "name"
        / "plugins"
        / "connection"
        / "broken_connection.py"
    )
    temp_collection_root = tmp_path / "collections" / "ansible_collections" / "ns"
    temp_collection_connection_dir = temp_collection_root / "name" / "plugins" / "connection"
    temp_collection_connection_dir.mkdir(parents=True)
    try:
        shutil.copy(connection_src, temp_collection_connection_dir / "broken_connection.py")

        proc = dap_client.launch(playbook, playbook_dir=tmp_path)

        dap_client.send(
            dap.SetExceptionBreakpointsRequest(filters=["on_unreachable"]), dap.SetExceptionBreakpointsResponse
        )
        dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

        resp = dap_client.wait_for_message(dap.ThreadEvent)
        assert resp.reason == "started"
        host_tid = resp.thread_id

        stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
        assert stopped_event.reason == dap.StoppedReason.EXCEPTION
        assert stopped_event.description == "Host unreachable"
        assert "Connection is broken" in str(stopped_event.text)
        assert stopped_event.thread_id == host_tid
        assert stopped_event.hit_breakpoint_ids == []

        st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host_tid), dap.StackTraceResponse)
        assert len(st_resp.stack_frames) == 1
        assert st_resp.total_frames == 1
        assert st_resp.stack_frames[0].name == "ping test"

        scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
        assert len(scope_resp.scopes) == 5
        assert scope_resp.scopes[0].name == "Module Result"
        assert scope_resp.scopes[1].name == "Module Options"
        assert scope_resp.scopes[2].name == "Task Variables"
        assert scope_resp.scopes[3].name == "Host Variables"
        assert scope_resp.scopes[4].name == "Global Variables"

        mod_res = dap_client.send(
            dap.VariablesRequest(variables_reference=scope_resp.scopes[0].variables_reference),
            dap.VariablesResponse,
        )

        to_find = {"unreachable", "msg", "changed"}
        for v in mod_res.variables:
            if v.name == "unreachable":
                assert v.value == "True"
                assert v.type == "bool"
                to_find.remove("unreachable")

            elif v.name == "msg":
                assert "Connection is broken" in v.value
                to_find.remove("msg")

            elif v.name == "changed":
                assert v.value == "False"
                assert v.type == "bool"
                to_find.remove("changed")

        assert len(to_find) == 0

        dap_client.send(dap.ContinueRequest(thread_id=host_tid), dap.ContinueResponse)

        resp = dap_client.wait_for_message(dap.ThreadEvent)
        assert resp.reason == "exited"

        dap_client.wait_for_message(dap.TerminatedEvent)

        play_out = proc.communicate()

    finally:
        shutil.rmtree(temp_collection_root)

    if (rc := proc.returncode) != 4:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_do_not_break_on_unreachable_ignore_unreachable(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
    vars:
        ansible_connection: ns.name.broken_connection
    ignore_unreachable: true
"""
    )

    connection_src = (
        pathlib.Path(__file__).parent.parent
        / "data"
        / "ansible_collections"
        / "ns"
        / "name"
        / "plugins"
        / "connection"
        / "broken_connection.py"
    )
    temp_collection_root = tmp_path / "collections" / "ansible_collections" / "ns"
    temp_collection_connection_dir = temp_collection_root / "name" / "plugins" / "connection"
    temp_collection_connection_dir.mkdir(parents=True)
    try:
        shutil.copy(connection_src, temp_collection_connection_dir / "broken_connection.py")

        proc = dap_client.launch(playbook, playbook_dir=tmp_path)

        dap_client.send(
            dap.SetExceptionBreakpointsRequest(filters=["on_unreachable"]), dap.SetExceptionBreakpointsResponse
        )
        dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

        resp = dap_client.wait_for_message(dap.ThreadEvent)
        assert resp.reason == "started"

        resp = dap_client.wait_for_message(dap.ThreadEvent)
        assert resp.reason == "exited"

        dap_client.wait_for_message(dap.TerminatedEvent)

        play_out = proc.communicate()

    finally:
        shutil.rmtree(temp_collection_root)

    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_do_not_break_on_unreachable_unset(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
    vars:
        ansible_connection: ns.name.broken_connection
"""
    )

    connection_src = (
        pathlib.Path(__file__).parent.parent
        / "data"
        / "ansible_collections"
        / "ns"
        / "name"
        / "plugins"
        / "connection"
        / "broken_connection.py"
    )
    temp_collection_root = tmp_path / "collections" / "ansible_collections" / "ns"
    temp_collection_connection_dir = temp_collection_root / "name" / "plugins" / "connection"
    temp_collection_connection_dir.mkdir(parents=True)
    try:
        shutil.copy(connection_src, temp_collection_connection_dir / "broken_connection.py")

        proc = dap_client.launch(playbook, playbook_dir=tmp_path)

        dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_error"]), dap.SetExceptionBreakpointsResponse)
        dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

        resp = dap_client.wait_for_message(dap.ThreadEvent)
        assert resp.reason == "started"

        resp = dap_client.wait_for_message(dap.ThreadEvent)
        assert resp.reason == "exited"

        dap_client.wait_for_message(dap.TerminatedEvent)

        play_out = proc.communicate()

    finally:
        shutil.rmtree(temp_collection_root)

    if (rc := proc.returncode) != 4:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_break_on_skipped(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
    when:
    - True
    - some_var.foo | default(False)

"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_skipped"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "started"
    host_tid = resp.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.EXCEPTION
    assert stopped_event.description == "Task skipped"
    assert (
        stopped_event.text
        == "Task skipped\nConditional result was False\n\nFalse condition: some_var.foo | default(False)"
    )
    assert stopped_event.thread_id == host_tid
    assert stopped_event.hit_breakpoint_ids == []

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping test"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    assert len(scope_resp.scopes) == 5
    assert scope_resp.scopes[0].name == "Module Result"
    assert scope_resp.scopes[1].name == "Module Options"
    assert scope_resp.scopes[2].name == "Task Variables"
    assert scope_resp.scopes[3].name == "Host Variables"
    assert scope_resp.scopes[4].name == "Global Variables"

    mod_res = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[0].variables_reference),
        dap.VariablesResponse,
    )

    to_find = {"changed", "skipped", "skip_reason", "false_condition"}
    for v in mod_res.variables:
        if v.name == "changed":
            assert v.value == "False"
            assert v.type == "bool"
            to_find.remove("changed")

        elif v.name == "skipped":
            assert v.value == "True"
            assert v.type == "bool"
            to_find.remove("skipped")

        elif v.name == "skip_reason":
            assert v.value == "'Conditional result was False'"
            to_find.remove("skip_reason")

        elif v.name == "false_condition":
            assert v.value == "'some_var.foo | default(False)'"
            to_find.remove("false_condition")

    assert len(to_find) == 0

    dap_client.send(dap.ContinueRequest(thread_id=host_tid), dap.ContinueResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_do_not_break_on_skipped_unset(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
    when:
    - True
    - some_var.foo | default(False)

"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_error"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "started"

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_step_over_after_exception_stop(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: skipped
    ping:
    when: false

  - name: after
    ping:

  - name: end
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_skipped"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    tid = dap_client.wait_for_message(dap.ThreadEvent).thread_id

    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.EXCEPTION

    dap_client.send(dap.NextRequest(thread_id=tid), dap.NextResponse)
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.STEP
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    assert [f.name for f in st_resp.stack_frames] == ["after"]

    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    proc.communicate()
    assert proc.returncode == 0, proc.format_output()


def test_break_on_error_in_rescue_section(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - block:
    - name: rescued
      fail:
        msg: rescued failure

    rescue:
    - name: not rescued
      fail:
        msg: rescue failure
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_error"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    tid = dap_client.wait_for_message(dap.ThreadEvent).thread_id

    # Only the failure in the rescue section stops, the block rescues the first.
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.EXCEPTION
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    assert [f.name for f in st_resp.stack_frames] == ["not rescued"]

    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    proc.communicate()
    assert proc.returncode == 2, proc.format_output()


def _three_host_inventory(tmp_path: pathlib.Path) -> None:
    (tmp_path / "inventory.ini").write_text(
        "\n".join(
            f"host{i} ansible_host=127.0.0.1 ansible_connection=local "
            + "ansible_python_interpreter={{ansible_playbook_python}}"
            for i in range(1, 4)
        )
    )


@pytest.mark.parametrize(
    "condition",
    [
        "inventory_hostname == 'host2'",
        "'boom host2' in result.msg",
    ],
)
def test_break_on_error_condition(
    condition: str,
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: all
  gather_facts: false
  tasks:
  - name: fail task
    fail:
      msg: boom {{ inventory_hostname }}
"""
    )
    _three_host_inventory(tmp_path)

    proc = dap_client.launch("main.yml", playbook_dir=tmp_path, playbook_args=["-i", "inventory.ini", "--forks", "1"])
    dap_client.send(
        dap.SetExceptionBreakpointsRequest(
            filter_options=[dap.ExceptionFilterOptions(filter_id="on_error", condition=condition)],
        ),
        dap.SetExceptionBreakpointsResponse,
    )
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    started: list[int] = []
    stopped: list[int] = []
    exited = 0
    while exited < 3:
        event = dap_client.wait_for_message(dap.Event)
        if isinstance(event, dap.ThreadEvent):
            if event.reason == "started":
                started.append(event.thread_id)
            else:
                exited += 1

        elif isinstance(event, dap.StoppedEvent):
            assert event.reason == dap.StoppedReason.EXCEPTION
            assert event.thread_id is not None
            stopped.append(event.thread_id)
            dap_client.send(dap.ContinueRequest(thread_id=event.thread_id), dap.ContinueResponse)

    # Only host2 stops, the hosts run in inventory order with 1 fork.
    assert stopped == [started[1]]

    dap_client.wait_for_message(dap.TerminatedEvent)
    proc.communicate()
    assert proc.returncode == 2, proc.format_output()


def test_break_on_error_empty_condition(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text("- hosts: localhost\n  gather_facts: false\n  tasks:\n  - fail:\n      msg: boom\n")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(
        dap.SetExceptionBreakpointsRequest(
            filter_options=[dap.ExceptionFilterOptions(filter_id="on_error", condition="")],
        ),
        dap.SetExceptionBreakpointsResponse,
    )
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    tid = dap_client.wait_for_message(dap.ThreadEvent).thread_id

    # An empty condition is the same as no condition.
    assert dap_client.wait_for_message(dap.StoppedEvent).reason == dap.StoppedReason.EXCEPTION
    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)
    proc.communicate()
    assert proc.returncode == 2, proc.format_output()


def test_exception_info(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: skipped task
    ping:
    when: false

  - name: ping task
    ping:

  - name: fail task
    fail:
      msg: boom
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(name="main.yml", path=str(playbook.absolute())),
            lines=[9],
            breakpoints=[dap.SourceBreakpoint(line=9)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    dap_client.send(
        dap.SetExceptionBreakpointsRequest(filters=["on_error", "on_skipped"]), dap.SetExceptionBreakpointsResponse
    )
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    tid = dap_client.wait_for_message(dap.ThreadEvent).thread_id

    # Skipped
    dap_client.wait_for_message(dap.StoppedEvent)
    info = dap_client.send(dap.ExceptionInfoRequest(thread_id=tid), dap.ExceptionInfoResponse)
    assert info.exception_id == "Task skipped"
    assert info.break_mode == "always"
    assert info.description is not None
    assert "False condition: False" in info.description
    assert info.details is not None
    assert info.details.type_name == "ansible.builtin.ping"
    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)

    # A breakpoint stop has no exception info.
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.BREAKPOINT
    err = dap_client.send(dap.ExceptionInfoRequest(thread_id=tid), dap.ErrorResponse)
    assert err.message == "The thread is not stopped on an exception"
    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)

    # Failed
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.EXCEPTION
    assert stopped.text is not None
    # Newer Ansible versions failed to format the error and showed its repr.
    assert "ErrorSummary(" not in stopped.text
    info = dap_client.send(dap.ExceptionInfoRequest(thread_id=tid), dap.ExceptionInfoResponse)
    assert info.exception_id == "Task failed"
    assert info.break_mode == "unhandled"
    assert info.description is not None
    assert "boom" in info.description
    assert info.details is not None
    assert info.details.type_name == "ansible.builtin.fail"
    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)

    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)
    proc.communicate()
    assert proc.returncode == 2, proc.format_output()


def test_restart_frame_on_error(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
      data: crash

  - name: after
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_error"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    tid = dap_client.wait_for_message(dap.ThreadEvent).thread_id

    # Re-run unchanged first, it fails again and must not be counted twice.
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.EXCEPTION
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    assert st_resp.stack_frames[0].can_restart

    dap_client.send(dap.RestartFrameRequest(frame_id=st_resp.stack_frames[0].id), dap.RestartFrameResponse)
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.RESTART
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    assert [f.name for f in st_resp.stack_frames] == ["ping test"]
    assert not st_resp.stack_frames[0].can_restart

    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.EXCEPTION

    # Fix the option on the failed result and re-run it.
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    frame_id = st_resp.stack_frames[0].id
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=frame_id), dap.ScopesResponse)
    assert scope_resp.scopes[1].name == "Module Options"
    dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[1].variables_reference,
            name="data",
            value="'fixed'",
        ),
        dap.SetVariableResponse,
    )

    dap_client.send(dap.RestartFrameRequest(frame_id=frame_id), dap.RestartFrameResponse)
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.RESTART

    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    stdout = proc.communicate()[0].decode()
    assert proc.returncode == 0, proc.format_output()
    assert "ok=2" in stdout
    assert "failed=0" in stdout
    assert stdout.count("TASK [ping test (restarted)]") == 2


def test_restart_frame_not_on_exception(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(name="main.yml", path=str(playbook.absolute())),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=5)],
        ),
        dap.SetBreakpointsResponse,
    )
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    tid = dap_client.wait_for_message(dap.ThreadEvent).thread_id

    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.BREAKPOINT
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    assert not st_resp.stack_frames[0].can_restart

    err = dap_client.send(dap.RestartFrameRequest(frame_id=st_resp.stack_frames[0].id), dap.ErrorResponse)
    assert "can be restarted" in (err.message or "")

    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    proc.communicate()
    assert proc.returncode == 0, proc.format_output()


def test_restart_frame_on_unreachable(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
    vars:
        ansible_connection: ns.name.broken_connection

  - name: after
    ping:
"""
    )

    connection_src = (
        pathlib.Path(__file__).parent.parent
        / "data"
        / "ansible_collections"
        / "ns"
        / "name"
        / "plugins"
        / "connection"
        / "broken_connection.py"
    )
    temp_collection_connection_dir = (
        tmp_path / "collections" / "ansible_collections" / "ns" / "name" / "plugins" / "connection"
    )
    temp_collection_connection_dir.mkdir(parents=True)
    shutil.copy(connection_src, temp_collection_connection_dir / "broken_connection.py")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(dap.SetExceptionBreakpointsRequest(filters=["on_unreachable"]), dap.SetExceptionBreakpointsResponse)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    tid = dap_client.wait_for_message(dap.ThreadEvent).thread_id

    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.description == "Host unreachable"

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    frame_id = st_resp.stack_frames[0].id
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=frame_id), dap.ScopesResponse)
    assert scope_resp.scopes[2].name == "Task Variables"
    dap_client.send(
        dap.SetVariableRequest(
            variables_reference=scope_resp.scopes[2].variables_reference,
            name="ansible_connection",
            value="'local'",
        ),
        dap.SetVariableResponse,
    )

    dap_client.send(dap.RestartFrameRequest(frame_id=frame_id), dap.RestartFrameResponse)
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.RESTART

    # The host is no longer unreachable so the next task runs.
    dap_client.send(dap.NextRequest(thread_id=tid), dap.NextResponse)
    stopped = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped.reason == dap.StoppedReason.STEP
    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=tid), dap.StackTraceResponse)
    assert [f.name for f in st_resp.stack_frames] == ["after"]

    dap_client.send(dap.ContinueRequest(thread_id=tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    stdout = proc.communicate()[0].decode()
    assert proc.returncode == 0, proc.format_output()
    assert "ok=2" in stdout
    assert "unreachable=0" in stdout
    assert "TASK [ping test (restarted)]" in stdout
