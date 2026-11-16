# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""Tests that client input never kills or hangs the DA server process."""

from __future__ import annotations

import pathlib
import subprocess
import sys

from dap_client import DAPClient, get_test_env

import ansibug.dap as dap


def test_unknown_request(
    dap_client: DAPClient,
) -> None:
    dap_client.send_raw({"seq": 100, "type": "request", "command": "pause", "arguments": {"threadId": 1}})

    err = dap_client.wait_for_message(dap.ErrorResponse)
    assert err.request_seq == 100
    assert err.command == "pause"
    assert err.message == "ansibug does not support the pause request"

    # The server is still processing requests.
    dap_client.send(dap.ThreadsRequest())
    err = dap_client.wait_for_message(dap.ErrorResponse)
    assert err.command == dap.Command.THREADS


def test_unexpected_client_messages(
    dap_client: DAPClient,
) -> None:
    # Responses the adapter did not ask for are ignored.
    dap_client.send(dap.ThreadsResponse(request_seq=999))
    dap_client.send(dap.ErrorResponse(command=dap.Command.RUN_IN_TERMINAL, request_seq=999, message="unexpected"))

    # The server is still processing requests.
    req = dap.ThreadsRequest()
    dap_client.send(req)
    err = dap_client.wait_for_message(dap.ErrorResponse)
    assert err.request_seq == req.seq


def test_request_after_playbook_ends(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text("- hosts: localhost\n  gather_facts: false\n  tasks: []\n")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    dap_client.wait_for_message(dap.TerminatedEvent)
    proc.communicate()

    # The debuggee is gone, the request is answered by the adapter.
    req = dap.ThreadsRequest()
    dap_client.send(req)
    err = dap_client.wait_for_message(dap.ErrorResponse)
    assert err.request_seq == req.seq
    assert err.message == "The threads request needs a launched or attached playbook"


def test_stdin_closed() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "ansibug", "dap"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=get_test_env(),
    )
    stdout, stderr = proc.communicate(timeout=10)

    assert proc.returncode == 0, stderr.decode()
    assert b'"event": "terminated"' in stdout


def test_run_in_terminal_failure(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text("- hosts: localhost\n  gather_facts: false\n  tasks: []\n")

    launch = dap.LaunchRequest(arguments={"playbook": str(playbook)})
    dap_client.send(launch)
    run_in_terminal = dap_client.wait_for_message(dap.RunInTerminalRequest)
    launch_script = pathlib.Path(run_in_terminal.args[1])
    assert launch_script.exists()

    dap_client.send(
        dap.ErrorResponse(
            command=dap.Command.RUN_IN_TERMINAL,
            request_seq=run_in_terminal.seq,
            message="terminal unavailable",
        )
    )

    err = dap_client.wait_for_message(dap.ErrorResponse)
    assert err.request_seq == launch.seq
    assert err.command == dap.Command.LAUNCH
    assert err.message == "The client failed to start the ansible-playbook process: terminal unavailable"
    dap_client.wait_for_message(dap.TerminatedEvent)
    assert not launch_script.exists()
