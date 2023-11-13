# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


def test_launch_no_playbook(
    dap_client: DAPClient,
) -> None:
    with pytest.raises(Exception, match="Expected playbook to be specified for launch"):
        dap_client.send(dap.LaunchRequest(arguments={}), dap.LaunchResponse)


def test_launch_invalid_console(
    dap_client: DAPClient,
) -> None:
    launch_args = {"playbook": "main.yml", "console": "invalid"}

    expected = "Unknown console value 'invalid' - expected integratedTerminal or externalTerminal"
    with pytest.raises(Exception, match=expected):
        dap_client.send(dap.LaunchRequest(arguments=launch_args), dap.LaunchResponse)


def test_launch_with_logging(
    request: pytest.FixtureRequest,
    tmp_path: pathlib.Path,
) -> None:
    dap_log_file = tmp_path / f"ansibug-{request.node.name}-dap.log"
    debuggee_log_file = tmp_path / f"ansibug-{request.node.name}-debuggee.log"

    with DAPClient(request.node.name, log_dir=tmp_path) as client:
        client.send(
            dap.InitializeRequest(
                adapter_id="ansibug",
                client_id="ansibug",
                client_name="Ansibug Conftest",
                locale="en",
                supports_variable_type=True,
                supports_run_in_terminal_request=True,
            ),
            dap.InitializeResponse,
        )

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

        proc = client.launch(playbook, playbook_dir=tmp_path)

        client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
        client.wait_for_message(dap.ThreadEvent)
        client.wait_for_message(dap.ThreadEvent)
        client.wait_for_message(dap.TerminatedEvent)

        play_out = proc.communicate()
        if rc := proc.returncode:
            raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")

        assert dap_log_file.exists()
        assert debuggee_log_file.exists()


def test_launch_with_timeout(
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

    expected = r"Timed out waiting for socket.accept\(\)"
    with pytest.raises(Exception, match=expected):
        dap_client.launch(
            playbook,
            playbook_dir=tmp_path,
            launch_options={
                "connectTimeout": 0.1,
            },
            do_not_launch=True,
        )


def test_launch_with_invalid_playbook(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
gather_facts: false
"""
    )

    proc = dap_client.launch(
        playbook,
        playbook_dir=tmp_path,
        expected_terminated=True,
    )

    proc.communicate()
    assert proc.returncode != 0


def test_launch_with_disconnect(
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

  - name: ping 2
    ping:

  - name: ping 3
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[8],
            breakpoints=[dap.SourceBreakpoint(line=8)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 1

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    dap_client.wait_for_message(dap.ThreadEvent)

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.DisconnectRequest(terminate_debuggee=False), dap.DisconnectResponse)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")

    assert "ok=3" in play_out[0].decode()
    assert "Unknown error in Debuggee send thread" not in play_out[1].decode()


def test_launch_with_terminate(
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

  - name: ping 2
    ping:

  - name: ping 3
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[8],
            breakpoints=[dap.SourceBreakpoint(line=8)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 1

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    dap_client.wait_for_message(dap.ThreadEvent)

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.TerminateRequest())

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    assert proc.returncode == 2
    stdout = play_out[0].decode()
    stderr = play_out[1].decode()

    assert "Debugger has requested the process to terminate" in stdout
    assert "ok=1" in stdout
    assert "Unknown error in Debuggee send thread" not in stderr


def test_launch_with_terminate_multiple_plays(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- name: play 1
  hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: ping 2
    ping:

  - name: ping 3
    ping:

- name: play 2
  hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 4
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[9],
            breakpoints=[dap.SourceBreakpoint(line=9)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 1

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    dap_client.wait_for_message(dap.ThreadEvent)

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.TerminateRequest())

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    assert proc.returncode == 2
    stdout = play_out[0].decode()
    stderr = play_out[1].decode()

    assert "PLAY [play 1]" in stdout
    assert "Debugger has requested the process to terminate" in stdout
    assert "PLAY [play 2]" not in stdout
    assert "ok=1" in stdout

    assert "Unknown error in Debuggee send thread" not in stderr
