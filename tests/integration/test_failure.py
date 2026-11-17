# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import sys

from dap_client import AnsibleProcess, DAPClient, get_test_env

import ansibug.dap as dap


def test_unknown_message(
    dap_client: DAPClient,
) -> None:
    # Sending a debuggee intended message before its connected is rejected
    # without ending the adapter.
    req = dap.ConfigurationDoneRequest()
    dap_client.send(req)
    resp = dap_client.wait_for_message(dap.ErrorResponse)

    assert resp.request_seq == req.seq
    assert resp.command == dap.Command.CONFIGURATION_DONE
    assert resp.message == "The configurationDone request needs a launched or attached playbook"

    # The adapter is still running.
    dap_client.send(dap.ThreadsRequest())
    dap_client.wait_for_message(dap.ErrorResponse)


def test_unknown_message_on_debuggee(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    proc = dap_client.launch(ping_playbook, playbook_dir=tmp_path)

    # After the debuggee is connected any requests are forwarded to it from the
    # DA server. This tests out how it reacts with an unknown request.
    err = dap_client.send(dap.LaunchRequest(arguments={}), dap.ErrorResponse)
    assert isinstance(err, dap.ErrorResponse)
    assert err.message
    assert "NotImplementedError: Debuggee does not support the LaunchRequest message" in err.message

    # We should be able to continue on as normal though
    dap_client.configuration_done()
    dap_client.wait_for_end(proc)


def test_connect_failure_does_not_hang(
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    proc = AnsibleProcess(
        [
            sys.executable,
            "-m",
            "ansibug",
            "connect",
            "--addr",
            f"uds://{tmp_path / 'missing.sock'}",
            str(ping_playbook),
        ],
        cwd=tmp_path,
        env=get_test_env(),
    )
    try:
        _, stderr = proc.communicate()
    finally:
        proc.stop()

    assert proc.returncode == 0, proc.format_output()
    assert b"Ansibug debug adapter is not connected" in stderr
