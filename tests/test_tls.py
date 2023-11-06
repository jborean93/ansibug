# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import datetime
import pathlib
import secrets
import shutil
import ssl
import string
import subprocess
import sys
import time

import pytest
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa, types
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from dap_client import DAPClient, get_test_env

import ansibug.dap as dap
from ansibug._debuggee import get_pid_info_path
from ansibug._tls import create_client_tls_context, create_server_tls_context

CA_PEM = "ca.pem"

CLIENT_INVALID = "client-invalid.pem"
CLIENT_COMBINED = "client-combined.pem"
CLIENT_CERT_ONLY = "client-cert.pem"
CLIENT_KEY_PLAINTEXT = "client-key-plaintext.pem"
CLIENT_KEY_ENCRYPTED = "client-key-encrypted.pem"

SERVER_COMBINED = "server-combined.pem"
SERVER_CERT_ONLY = "server-cert.pem"
SERVER_KEY_PLAINTEXT = "server-key-plaintext.pem"
SERVER_KEY_ENCRYPTED = "server-key-encrypted.pem"

KEY_PASSWORD = "".join(secrets.choice(string.ascii_letters + string.digits) for i in range(16))


def _generate_cert(
    subject: str,
    issuer: tuple[x509.Certificate, types.CertificateIssuerPrivateKeyTypes] | None = None,
    extensions: list[tuple[x509.ExtensionType, bool]] | None = None,
) -> tuple[x509.Certificate, types.CertificateIssuerPrivateKeyTypes]:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )

    subject_name = x509.Name(
        [
            x509.NameAttribute(x509.NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(x509.NameOID.STATE_OR_PROVINCE_NAME, "State"),
            x509.NameAttribute(x509.NameOID.LOCALITY_NAME, "City"),
            x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, "Ansible"),
            x509.NameAttribute(x509.NameOID.COMMON_NAME, subject),
        ]
    )

    issuer_name = subject_name
    sign_key: types.CertificateIssuerPrivateKeyTypes = private_key
    if issuer:
        issuer_name = issuer[0].subject
        sign_key = issuer[1]

    now = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    builder = x509.CertificateBuilder()
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(issuer_name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=365))
    )
    if extensions:
        for ext, critical in extensions:
            builder = builder.add_extension(ext, critical)

    return builder.sign(sign_key, SHA256()), private_key


def _serialize_cert(
    cert: x509.Certificate,
    key: types.CertificateIssuerPrivateKeyTypes,
    *,
    cert_only: pathlib.Path | None = None,
    combined: pathlib.Path | None = None,
    key_plaintext: pathlib.Path | None = None,
    key_encrypted: pathlib.Path | None = None,
) -> None:
    b_pub_key = cert.public_bytes(Encoding.PEM)
    b_key_plaintext = key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=NoEncryption(),
    )

    if cert_only:
        with open(cert_only, mode="wb") as fd:
            fd.write(b_pub_key)

    if combined:
        with open(combined, mode="wb") as fd:
            fd.write(b_key_plaintext)
            fd.write(b_pub_key)

    if key_plaintext:
        with open(key_plaintext, mode="wb") as fd:
            fd.write(b_key_plaintext)

    if key_encrypted:
        b_key_encrypted = key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=BestAvailableEncryption(KEY_PASSWORD.encode()),
        )
        with open(key_encrypted, mode="wb") as fd:
            fd.write(b_key_encrypted)


@pytest.fixture(scope="session")
def certs(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    ca = _generate_cert(
        "ansibug-ca",
        extensions=[(x509.BasicConstraints(ca=True, path_length=None), True)],
    )
    server = _generate_cert(
        "ansibug-server",
        issuer=ca,
        extensions=[(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)],
    )
    client = _generate_cert(
        "ansibug-client",
        issuer=ca,
    )
    client_self_signed = _generate_cert("selfsigned-client")

    cert_dir = tmp_path_factory.mktemp(basename="certificates")

    _serialize_cert(*ca, cert_only=cert_dir / CA_PEM)
    _serialize_cert(
        *server,
        cert_only=cert_dir / SERVER_CERT_ONLY,
        combined=cert_dir / SERVER_COMBINED,
        key_encrypted=cert_dir / SERVER_KEY_ENCRYPTED,
        key_plaintext=cert_dir / SERVER_KEY_PLAINTEXT,
    )
    _serialize_cert(
        *client,
        cert_only=cert_dir / CLIENT_CERT_ONLY,
        combined=cert_dir / CLIENT_COMBINED,
        key_encrypted=cert_dir / CLIENT_KEY_ENCRYPTED,
        key_plaintext=cert_dir / CLIENT_KEY_PLAINTEXT,
    )
    _serialize_cert(*client_self_signed, combined=cert_dir / CLIENT_INVALID)

    return cert_dir


@pytest.mark.parametrize(
    "scenario",
    ["combined", "separate_plaintext", "separate_encrypted"],
)
def test_attach_tls(
    scenario: str,
    dap_client: DAPClient,
    certs: pathlib.Path,
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
        ansibug_args += ["--tls-cert", str(certs / SERVER_COMBINED)]
    elif scenario == "separate_plaintext":
        ansibug_args += [
            "--tls-cert",
            str(certs / SERVER_CERT_ONLY),
            "--tls-key",
            str(certs / SERVER_KEY_PLAINTEXT),
        ]
    else:
        ansibug_args += [
            "--tls-cert",
            str(certs / SERVER_CERT_ONLY),
            "--tls-key",
            str(certs / SERVER_KEY_ENCRYPTED),
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


@pytest.mark.parametrize(
    "scenario",
    ["combined", "separate_plaintext", "separate_encrypted"],
)
def test_attach_tls_client_auth(
    scenario: str,
    dap_client: DAPClient,
    certs: pathlib.Path,
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
        str(certs / SERVER_COMBINED),
        "--tls-client-ca",
        str(certs / CA_PEM),
    ]

    attach_options = {"tlsVerification": "ignore"}
    if scenario == "combined":
        attach_options["tlsCertificate"] = str(certs / CLIENT_COMBINED)

    elif scenario == "separate_plaintext":
        attach_options["tlsCertificate"] = str(certs / CLIENT_CERT_ONLY)
        attach_options["tlsKey"] = str(certs / CLIENT_KEY_PLAINTEXT)

    else:
        attach_options["tlsCertificate"] = str(certs / CLIENT_COMBINED)
        attach_options["tlsKey"] = str(certs / CLIENT_KEY_ENCRYPTED)
        attach_options["tlsKeyPassword"] = KEY_PASSWORD

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
    certs: pathlib.Path,
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
        str(certs / SERVER_COMBINED),
        "--tls-client-ca",
        str(certs / CA_PEM),
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
                    "tlsCertificate": str(certs / CLIENT_COMBINED),
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


def test_client_verify(certs: pathlib.Path) -> None:
    client = create_client_tls_context(verify="verify")
    client.load_verify_locations(cafile=str(certs / CA_PEM))

    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED))
    _do_tls_handshake(client, server, "localhost")


def test_client_ignore(certs: pathlib.Path) -> None:
    client = create_client_tls_context(verify="ignore")
    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED))
    _do_tls_handshake(client, server, "invalid")


def test_client_ca_file(certs: pathlib.Path) -> None:
    client = create_client_tls_context(verify=str(certs / CA_PEM))
    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED))
    _do_tls_handshake(client, server, "localhost")


def test_client_ca_dir(
    certs: pathlib.Path,
) -> None:
    if not shutil.which("openssl"):
        pytest.skip(reason="test requires the openssl command")

    # Using a directory requires the files to be named in a special format.
    ca_file = str((certs / CA_PEM).absolute())
    hash_out = subprocess.run(
        ["openssl", "x509", "-hash", "-noout", "-in", ca_file],
        check=True,
        capture_output=True,
        text=True,
    )

    ca_dir = certs / "ca_dir"
    ca_dir.mkdir()
    shutil.copyfile(ca_file, str((ca_dir / f"{hash_out.stdout.strip()}.0").absolute()))

    client = create_client_tls_context(verify=str(ca_dir.absolute()))
    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED))
    _do_tls_handshake(client, server, "localhost")


@pytest.mark.parametrize(
    ["scenario"],
    [
        ("combined",),
        ("key_plaintext",),
        ("key_encrypted",),
    ],
)
def test_server_requires_client_cert(
    scenario: str,
    certs: pathlib.Path,
) -> None:
    ca = str(certs / CA_PEM)
    client_kwargs = {}
    if scenario == "combined":
        client_kwargs["certfile"] = str(certs / CLIENT_COMBINED)
    elif scenario == "key_plaintext":
        client_kwargs["certfile"] = str(certs / CLIENT_CERT_ONLY)
        client_kwargs["keyfile"] = str(certs / CLIENT_KEY_PLAINTEXT)
    else:
        client_kwargs["certfile"] = str(certs / CLIENT_CERT_ONLY)
        client_kwargs["keyfile"] = str(certs / CLIENT_KEY_ENCRYPTED)
        client_kwargs["password"] = KEY_PASSWORD

    client = create_client_tls_context(verify=ca, **client_kwargs)
    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED), ca_trust=ca)
    _do_tls_handshake(client, server, "localhost")


def test_client_invalid_ca(certs: pathlib.Path) -> None:
    client = create_client_tls_context()
    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED))

    with pytest.raises(ssl.SSLCertVerificationError):
        _do_tls_handshake(client, server, "localhost")


def test_client_invalid_cn(certs: pathlib.Path) -> None:
    client = create_client_tls_context(verify=str(certs / SERVER_CERT_ONLY))
    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED))

    with pytest.raises(ssl.SSLCertVerificationError):
        _do_tls_handshake(client, server, "invalid")


def test_client_invalid_path() -> None:
    with pytest.raises(ValueError, match="Certificate CA verify path '/tmp/fake path' does not exist"):
        create_client_tls_context(verify="/tmp/fake path")


def test_server_no_client_cert(certs: pathlib.Path) -> None:
    ca = str(certs / CA_PEM)
    client = create_client_tls_context(verify=ca)
    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED), ca_trust=ca)

    with pytest.raises(ssl.SSLError, match="peer did not return a certificate"):
        _do_tls_handshake(client, server, "localhost")


def test_server_invalid_client_cert(certs: pathlib.Path) -> None:
    ca = str(certs / CA_PEM)
    client = create_client_tls_context(verify=ca, certfile=str(certs / CLIENT_INVALID))
    server = create_server_tls_context(certfile=str(certs / SERVER_COMBINED), ca_trust=ca)

    with pytest.raises(ssl.SSLError, match="certificate verify failed"):
        _do_tls_handshake(client, server, "localhost")


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
