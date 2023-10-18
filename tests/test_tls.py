# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import datetime
import pathlib
import secrets
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
    load_pem_private_key,
)
from dap_client import DAPClient

import ansibug.dap as dap

COMBINED = "combined.pem"
CERT_ONLY = "cert.pem"
KEY_PLAINTEXT = "key-plaintext.pem"
KEY_ENCRYPTED = "key-encrypted.pem"
KEY_PASSWORD = "key-password.txt"


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

    alphabet = string.ascii_letters + string.digits + string.punctuation
    key_password = "".join(secrets.choice(alphabet) for i in range(16)).encode()

    pub_key = cert.public_bytes(Encoding.PEM)
    key_plaintext = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )
    key_encrypted = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=BestAvailableEncryption(key_password),
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

    with open(cert_dir / KEY_PASSWORD, mode="wb") as fd:
        fd.write(key_password)

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
        key_password = (keypair / KEY_PASSWORD).read_text()
        ansibug_args += [
            "--tls-cert",
            str(keypair / CERT_ONLY),
            "--tls-key",
            str(keypair / KEY_ENCRYPTED),
            "--tls-key-pass",
            key_password,
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
