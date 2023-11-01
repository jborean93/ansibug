# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import datetime
import pathlib
import secrets
import ssl
import string

import pytest
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from dap_client import DAPClient

import ansibug.dap as dap
from ansibug._tls import create_client_tls_context, create_server_tls_context

COMBINED = "combined.pem"
CERT_ONLY = "cert.pem"
KEY_PLAINTEXT = "key-plaintext.pem"
KEY_ENCRYPTED = "key-encrypted.pem"
KEY_PASSWORD = "".join(secrets.choice(string.ascii_letters + string.digits) for i in range(16))


@pytest.fixture(scope="function")
def keypair(tmp_path: pathlib.Path) -> pathlib.Path:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, "AU"),
            x509.NameAttribute(x509.NameOID.STATE_OR_PROVINCE_NAME, "Queensland"),
            x509.NameAttribute(x509.NameOID.LOCALITY_NAME, "Brisbane"),
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Ansible"),
            x509.NameAttribute(x509.NameOID.COMMON_NAME, "ansibug"),
        ]
    )

    now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(private_key, SHA256())
    )

    pub_key = cert.public_bytes(Encoding.PEM)
    key_plaintext = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )
    key_encrypted = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=BestAvailableEncryption(KEY_PASSWORD.encode()),
    )

    cert_dir = tmp_path / "certificates"
    cert_dir.mkdir()

    with open(cert_dir / COMBINED, mode="wb") as fd:
        fd.write(key_plaintext)
        fd.write(pub_key)

    with open(cert_dir / CERT_ONLY, mode="wb") as fd:
        fd.write(pub_key)

    with open(cert_dir / KEY_PLAINTEXT, mode="wb") as fd:
        fd.write(key_plaintext)

    with open(cert_dir / KEY_ENCRYPTED, mode="wb") as fd:
        fd.write(key_encrypted)

    return cert_dir


@pytest.mark.parametrize("scenario", ["combined", "separate_plaintext", "separate_encrypted"])
def test_attach_tls(
    scenario: str,
    dap_client: DAPClient,
    keypair: pathlib.Path,
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
        ansibug_args += ["--tls-cert", str(keypair / COMBINED)]
    elif scenario == "separate_plaintext":
        ansibug_args += [
            "--tls-cert",
            str(keypair / CERT_ONLY),
            "--tls-key",
            str(keypair / KEY_PLAINTEXT),
        ]
    else:
        ansibug_args += [
            "--tls-cert",
            str(keypair / CERT_ONLY),
            "--tls-key",
            str(keypair / KEY_ENCRYPTED),
            "--tls-key-pass",
            KEY_PASSWORD,
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


def test_client_verify(keypair: pathlib.Path) -> None:
    client = create_client_tls_context(verify="verify")
    client.load_verify_locations(cafile=str(keypair / CERT_ONLY))

    server = create_server_tls_context(certfile=str(keypair / COMBINED))
    _do_tls_handshake(client, server, "localhost")


def test_client_ignore(keypair: pathlib.Path) -> None:
    client = create_client_tls_context(verify="ignore")
    server = create_server_tls_context(certfile=str(keypair / COMBINED))
    _do_tls_handshake(client, server, "invalid")


def test_client_ca_file(keypair: pathlib.Path) -> None:
    client = create_client_tls_context(verify=str(keypair / CERT_ONLY))
    server = create_server_tls_context(certfile=str(keypair / COMBINED))
    _do_tls_handshake(client, server, "localhost")


def test_client_invalid_ca(keypair: pathlib.Path) -> None:
    client = create_client_tls_context()
    server = create_server_tls_context(certfile=str(keypair / COMBINED))

    with pytest.raises(ssl.SSLCertVerificationError):
        _do_tls_handshake(client, server, "localhost")


def test_client_invalid_cn(keypair: pathlib.Path) -> None:
    client = create_client_tls_context(verify=str(keypair / CERT_ONLY))
    server = create_server_tls_context(certfile=str(keypair / COMBINED))

    with pytest.raises(ssl.SSLCertVerificationError):
        _do_tls_handshake(client, server, "invalid")


def test_client_invalid_path() -> None:
    with pytest.raises(ValueError, match="verify location path '/tmp/fake path' does not exist"):
        create_client_tls_context(verify="/tmp/fake path")


def _do_tls_handshake(
    client: ssl.SSLContext,
    server: ssl.SSLContext,
    target: str,
) -> None:
    c_in = ssl.MemoryBIO()
    c_out = ssl.MemoryBIO()
    s_in = ssl.MemoryBIO()
    s_out = ssl.MemoryBIO()
    c = client.wrap_bio(c_in, c_out, server_side=False, server_hostname=target)
    s = server.wrap_bio(s_in, s_out, server_side=True)

    in_token: bytes | None = None
    while True:
        if in_token:
            c_in.write(in_token)

        out_token: bytes | None = None
        try:
            c.do_handshake()
        except ssl.SSLWantReadError:
            pass

        out_token = c_out.read()
        if not out_token:
            break

        s_in.write(out_token)
        try:
            s.do_handshake()
        except ssl.SSLWantReadError:
            pass

        in_token = s_out.read()
        if not in_token:
            break

    assert c.version() == s.version()
    assert c.cipher() == s.cipher()
