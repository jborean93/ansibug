# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

from dap_client import DAPClient

import ansibug.dap as dap


def test_unknown_message(
    dap_client: DAPClient,
) -> None:
    # Sending a debuggee intended message before its connected will have the
    # adapter fail as expected
    dap_client.send(dap.ConfigurationDoneRequest())
    resp = dap_client.wait_for_message(dap.ErrorResponse)

    assert isinstance(resp, dap.ErrorResponse)
    assert resp.message
    assert "NotImplementedError: Debug Adapter does not support the ConfigurationDoneRequest message" in resp.message


def test_unknown_message_on_debuggee(
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

    # After the debuggee is connected any requests are forwarded to it from the
    # DA server. This tests out how it reacts with an unknown request.
    err = dap_client.send(dap.LaunchRequest(arguments={}), dap.ErrorResponse)
    assert isinstance(err, dap.ErrorResponse)
    assert err.message
    assert "NotImplementedError: Debuggee does not support the LaunchRequest message" in err.message

    # We should be able to continue on as normal though
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")
