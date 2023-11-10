# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import subprocess
import sys
import time

import pytest
from dap_client import DAPClient, get_test_env
from tls_info import CertFixture

import ansibug.dap as dap
from ansibug._debuggee import get_pid_info_path


@pytest.mark.parametrize(
    "scenario",
    ["combined", "separate_plaintext", "separate_encrypted"],
)
def test_attach_tls(
    scenario: str,
    dap_client: DAPClient,
    certs: CertFixture,
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

    ansibug_args = ["--wrap-tls"]
    if scenario == "combined":
        ansibug_args += ["--tls-cert", str(certs.server_combined)]
    elif scenario == "separate_plaintext":
        ansibug_args += [
            "--tls-cert",
            str(certs.server_cert_only),
            "--tls-key",
            str(certs.server_key_plaintext),
        ]
    else:
        ansibug_args += [
            "--tls-cert",
            str(certs.server_cert_only),
            "--tls-key",
            str(certs.server_key_encrypted),
            "--tls-key-pass",
            certs.password,
        ]

    proc = dap_client.attach(
        playbook,
        playbook_dir=tmp_path,
        ansibug_args=ansibug_args,
        attach_options={
            "tlsVerification": "ignore",
        },
    )

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=5)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.ContinueRequest(thread_id=thread_event.thread_id), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


@pytest.mark.parametrize(
    "scenario",
    ["combined", "separate_plaintext", "separate_encrypted"],
)
def test_attach_tls_client_auth(
    scenario: str,
    dap_client: DAPClient,
    certs: CertFixture,
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

    ansibug_args = [
        "--wrap-tls",
        "--tls-cert",
        str(certs.server_combined),
        "--tls-client-ca",
        str(certs.ca),
    ]

    attach_options = {"tlsVerification": "ignore"}
    if scenario == "combined":
        attach_options["tlsCertificate"] = str(certs.client_combined)

    elif scenario == "separate_plaintext":
        attach_options["tlsCertificate"] = str(certs.client_cert_only)
        attach_options["tlsKey"] = str(certs.client_key_plaintext)

    else:
        attach_options["tlsCertificate"] = str(certs.client_combined)
        attach_options["tlsKey"] = str(certs.client_key_encrypted)
        attach_options["tlsKeyPassword"] = certs.password

    proc = dap_client.attach(
        playbook,
        playbook_dir=tmp_path,
        ansibug_args=ansibug_args,
        attach_options=attach_options,
    )

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=5)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.ContinueRequest(thread_id=thread_event.thread_id), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_attach_tls_client_auth_initial_rejection(
    request: pytest.FixtureRequest,
    certs: CertFixture,
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

    ansibug_args = [
        sys.executable,
        "-m",
        "ansibug",
        "listen",
        "--wrap-tls",
        "--tls-cert",
        str(certs.server_combined),
        "--tls-client-ca",
        str(certs.ca),
        str(playbook),
    ]

    new_environment = get_test_env()
    proc = subprocess.Popen(
        ansibug_args,
        cwd=str(tmp_path),
        env=new_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    pid_path = get_pid_info_path(proc.pid)
    for _ in range(10):
        if pid_path.exists():
            break
        elif (rc := proc.poll()) is not None:
            stdout, stderr = proc.communicate()
            raise Exception(
                f"Error when launching new ansible-playbook process\nRC: {rc}\nSTDOUT\n{stdout.decode()}\nSTDERR\n{stderr.decode()}"
            )

        time.sleep(1)
    else:
        proc.kill()
        raise Exception("timed out waiting for proc pid")

    attach_arguments = {"processId": proc.pid, "tlsVerification": "ignore"}

    with DAPClient(request.node.name, log_dir=None) as dap_client:
        dap_client.send(
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

        # This will fail as no client cert is provided
        with pytest.raises(Exception, match="certificate required"):
            dap_client.send(dap.AttachRequest(arguments=attach_arguments), dap.AttachResponse)

    with DAPClient(request.node.name, log_dir=None) as dap_client:
        dap_client.send(
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

        # This should now work as the client cert is provided
        dap_client.send(
            dap.AttachRequest(
                arguments=attach_arguments
                | {
                    "tlsCertificate": str(certs.client_combined),
                }
            ),
            dap.AttachResponse,
        )
        dap_client.wait_for_message(dap.InitializedEvent)

        dap_client.send(
            dap.SetBreakpointsRequest(
                source=dap.Source(
                    name="main.yml",
                    path=str(playbook.absolute()),
                ),
                lines=[5],
                breakpoints=[dap.SourceBreakpoint(line=5)],
                source_modified=False,
            ),
            dap.SetBreakpointsResponse,
        )
        dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
        thread_event = dap_client.wait_for_message(dap.ThreadEvent)
        dap_client.wait_for_message(dap.StoppedEvent)
        dap_client.send(dap.ContinueRequest(thread_id=thread_event.thread_id), dap.ContinueResponse)
        dap_client.wait_for_message(dap.ThreadEvent)
        dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")
