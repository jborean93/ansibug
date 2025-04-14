# Copyright (c) 2025 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import shutil

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
        assert stopped_event.text == "Connection is broken"
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
                assert v.value == "'Connection is broken'"
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
