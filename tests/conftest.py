# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import os
import pathlib
import secrets
import string
import sys
import typing as t

import pytest
from cryptography import x509

sys.path.append(str(pathlib.Path(__file__).parent / "utils"))

from dap_client import DAPClient
from tls_info import CertFixture, generate_cert, serialize_cert


@pytest.fixture(scope="function")
def dap_client(
    request: pytest.FixtureRequest,
) -> collections.abc.Iterator[DAPClient]:
    # Set to a directory to get the debug logs of the DA server and debuggee.
    log_dir = pathlib.Path(d) if (d := os.environ.get("ANSIBUG_TEST_LOG_DIR")) else None
    with DAPClient(request.node.name, log_dir=log_dir) as client:
        client.initialize()

        yield client


@pytest.fixture(params=["linear", "free", "host_pinned"])
def strategy(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Runs the test with each builtin strategy, used by the tests of what a strategy can affect."""
    # The Ansible process is started with the env of the test process.
    monkeypatch.setenv("ANSIBLE_STRATEGY", request.param)
    return t.cast(str, request.param)


@pytest.fixture(scope="session")
def certs(tmp_path_factory: pytest.TempPathFactory) -> CertFixture:
    ca_key_usage = x509.KeyUsage(
        digital_signature=True,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=True,
        crl_sign=True,
        encipher_only=False,
        decipher_only=False,
    )
    ca = generate_cert(
        "ansibug-ca",
        extensions=[
            (x509.BasicConstraints(ca=True, path_length=None), True),
            (ca_key_usage, True),
        ],
    )
    ca_aki = x509.AuthorityKeyIdentifier.from_issuer_public_key(ca[0].public_key())  # pyright: ignore[reportArgumentType]

    server = generate_cert(
        "ansibug-server",
        issuer=ca,
        extensions=[
            (x509.SubjectAlternativeName([x509.DNSName("localhost")]), False),
            (ca_aki, False),
        ],
    )
    client = generate_cert(
        "ansibug-client",
        issuer=ca,
        extensions=[(ca_aki, False)],
    )
    client_self_signed = generate_cert("selfsigned-client")

    cert_dir = tmp_path_factory.mktemp(basename="certificates")
    test_certs = CertFixture(
        ca=cert_dir / "ca.pem",
        password="".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16)),
        client_invalid=cert_dir / "client-invalid.pem",
        client_combined=cert_dir / "client-combined.pem",
        client_cert_only=cert_dir / "client-cert.pem",
        client_key_encrypted=cert_dir / "client-key-encrypted.pem",
        client_key_plaintext=cert_dir / "client-key-plaintext.pem",
        server_combined=cert_dir / "server-combined.pem",
        server_cert_only=cert_dir / "server-cert.pem",
        server_key_encrypted=cert_dir / "server-key-encrypted.pem",
        server_key_plaintext=cert_dir / "server-key-plaintext.pem",
    )

    serialize_cert(*ca, cert_only=test_certs.ca)
    serialize_cert(
        *server,
        cert_only=test_certs.server_cert_only,
        combined=test_certs.server_combined,
        key_encrypted=test_certs.server_key_encrypted,
        key_plaintext=test_certs.server_key_plaintext,
        key_password=test_certs.password,
    )
    serialize_cert(
        *client,
        cert_only=test_certs.client_cert_only,
        combined=test_certs.client_combined,
        key_encrypted=test_certs.client_key_encrypted,
        key_plaintext=test_certs.client_key_plaintext,
        key_password=test_certs.password,
    )
    serialize_cert(*client_self_signed, combined=test_certs.client_invalid)

    return test_certs


@pytest.fixture(scope="function")
def ping_playbook(tmp_path: pathlib.Path) -> pathlib.Path:
    """A playbook on localhost with a single ping task on line 5."""
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
    return playbook
