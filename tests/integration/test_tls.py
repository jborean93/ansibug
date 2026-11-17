# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

import pytest
from dap_client import DAPClient, DAPErrorResponse, start_listen
from tls_info import CertFixture

import ansibug.dap as dap


@pytest.mark.parametrize(
    "scenario",
    ["combined", "separate_plaintext", "separate_encrypted"],
)
def test_attach_tls(
    scenario: str,
    dap_client: DAPClient,
    certs: CertFixture,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
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
        ping_playbook,
        playbook_dir=tmp_path,
        ansibug_args=ansibug_args,
        attach_options={
            "tlsVerification": "ignore",
        },
    )

    dap_client.set_breakpoints(ping_playbook, 5)
    tid = dap_client.configuration_done()
    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.continue_to_end(proc, tid)


@pytest.mark.parametrize(
    "scenario",
    ["combined", "separate_plaintext", "separate_encrypted"],
)
def test_attach_tls_client_auth(
    scenario: str,
    dap_client: DAPClient,
    certs: CertFixture,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
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
        ping_playbook,
        playbook_dir=tmp_path,
        ansibug_args=ansibug_args,
        attach_options=attach_options,
    )

    dap_client.set_breakpoints(ping_playbook, 5)
    tid = dap_client.configuration_done()
    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.continue_to_end(proc, tid)


def test_attach_tls_client_auth_initial_rejection(
    request: pytest.FixtureRequest,
    certs: CertFixture,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    ansibug_args = ["--wrap-tls", "--tls-cert", str(certs.server_combined), "--tls-client-ca", str(certs.ca)]
    proc = start_listen(ping_playbook, tmp_path, ansibug_args=ansibug_args)
    try:
        attach_arguments = {"processId": proc.pid, "tlsVerification": "ignore"}

        with DAPClient(request.node.name, log_dir=None) as dap_client:
            dap_client.initialize()

            # This will fail as no client cert is provided
            with pytest.raises(DAPErrorResponse, match="certificate required"):
                dap_client.send(dap.AttachRequest(arguments=attach_arguments), dap.AttachResponse)

        with DAPClient(request.node.name, log_dir=None) as dap_client:
            dap_client.initialize()

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

            dap_client.set_breakpoints(ping_playbook, 5)
            tid = dap_client.configuration_done()
            dap_client.wait_for_message(dap.StoppedEvent)
            dap_client.continue_to_end(proc, tid)

    finally:
        proc.stop()
