# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import pathlib
import subprocess
import sys

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


@pytest.mark.parametrize("attach_by_address", [False, True])
def test_attach_playbook(
    attach_by_address: bool,
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

    proc = dap_client.attach(
        playbook,
        playbook_dir=tmp_path,
        attach_by_address=attach_by_address,
    )

    resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=6)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(resp.breakpoints) == 1
    assert resp.breakpoints[0].verified
    assert resp.breakpoints[0].line == 5
    assert resp.breakpoints[0].end_line == 5
    bid = resp.breakpoints[0].id

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_run_with_listen_no_client(
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
    actual = subprocess.run(
        [sys.executable, "-m", "ansibug", "listen", "--no-wait", str(playbook)],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if actual.returncode:
        raise Exception(f"Playbook failed {actual.returncode}\nSTDOUT: {actual.stdout}\nSTDERR: {actual.stderr}")


def test_attach_invalid_pid(
    dap_client: DAPClient,
) -> None:
    attach_args = {
        "processId": 0,
    }

    with pytest.raises(Exception, match="Failed to find process pid file at "):
        dap_client.send(dap.AttachRequest(arguments=attach_args), dap.AttachResponse)


def test_attach_no_pid_or_port(
    dap_client: DAPClient,
) -> None:
    attach_args = {
        "address": "localhost",
    }

    with pytest.raises(Exception, match="Expected processId or address and port to be specified for attach"):
        dap_client.send(dap.AttachRequest(arguments=attach_args), dap.AttachResponse)
