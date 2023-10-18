# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import pathlib

from dap_client import DAPClient

import ansibug.dap as dap


def test_attach_playbook(
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

    proc = dap_client.attach(playbook, playbook_dir=tmp_path)

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
