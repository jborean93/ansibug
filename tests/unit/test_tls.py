# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import shutil
import ssl
import subprocess

import pytest
from tls_info import CertFixture

from ansibug._tls import create_client_tls_context, create_server_tls_context


def test_client_verify(certs: CertFixture) -> None:
    client = create_client_tls_context(verify="verify")
    client.load_verify_locations(cafile=str(certs.ca))

    server = create_server_tls_context(certfile=str(certs.server_combined))
    _do_tls_handshake(client, server, "localhost")


def test_client_ignore(certs: CertFixture) -> None:
    client = create_client_tls_context(verify="ignore")
    server = create_server_tls_context(certfile=str(certs.server_combined))
    _do_tls_handshake(client, server, "invalid")


def test_client_ca_file(certs: CertFixture) -> None:
    client = create_client_tls_context(verify=str(certs.ca))
    server = create_server_tls_context(certfile=str(certs.server_combined))
    _do_tls_handshake(client, server, "localhost")


def test_client_ca_dir(
    certs: CertFixture,
    tmp_path: pathlib.Path,
) -> None:
    if not shutil.which("openssl"):
        pytest.skip(reason="test requires the openssl command")

    # Using a directory requires the files to be named in a special format.
    ca_file = str(certs.ca)
    hash_out = subprocess.run(
        ["openssl", "x509", "-hash", "-noout", "-in", ca_file],
        check=True,
        capture_output=True,
        text=True,
    )

    ca_dir = tmp_path / "ca_dir"
    ca_dir.mkdir()
    shutil.copyfile(ca_file, str((ca_dir / f"{hash_out.stdout.strip()}.0").absolute()))

    client = create_client_tls_context(verify=str(ca_dir.absolute()))
    server = create_server_tls_context(certfile=str(certs.server_combined))
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
    certs: CertFixture,
) -> None:
    ca = str(certs.ca)
    client_kwargs = {}
    if scenario == "combined":
        client_kwargs["certfile"] = str(certs.client_combined)
    elif scenario == "key_plaintext":
        client_kwargs["certfile"] = str(certs.client_cert_only)
        client_kwargs["keyfile"] = str(certs.client_key_plaintext)
    else:
        client_kwargs["certfile"] = str(certs.client_cert_only)
        client_kwargs["keyfile"] = str(certs.client_key_encrypted)
        client_kwargs["password"] = certs.password

    client = create_client_tls_context(verify=ca, **client_kwargs)
    server = create_server_tls_context(certfile=str(certs.server_combined), ca_trust=ca)
    _do_tls_handshake(client, server, "localhost")


def test_client_invalid_ca(certs: CertFixture) -> None:
    client = create_client_tls_context()
    server = create_server_tls_context(certfile=str(certs.server_combined))

    with pytest.raises(ssl.SSLCertVerificationError):
        _do_tls_handshake(client, server, "localhost")


def test_client_invalid_cn(certs: CertFixture) -> None:
    client = create_client_tls_context(verify=str(certs.server_cert_only))
    server = create_server_tls_context(certfile=str(certs.server_combined))

    with pytest.raises(ssl.SSLCertVerificationError):
        _do_tls_handshake(client, server, "invalid")


def test_client_invalid_path() -> None:
    with pytest.raises(ValueError, match="Certificate CA verify path '/tmp/fake path' does not exist"):
        create_client_tls_context(verify="/tmp/fake path")


def test_server_no_client_cert(certs: CertFixture) -> None:
    ca = str(certs.ca)
    client = create_client_tls_context(verify=ca)
    server = create_server_tls_context(certfile=str(certs.server_combined), ca_trust=ca)

    with pytest.raises(ssl.SSLError, match="peer did not return a certificate"):
        _do_tls_handshake(client, server, "localhost")


def test_server_invalid_client_cert(certs: CertFixture) -> None:
    ca = str(certs.ca)
    client = create_client_tls_context(verify=ca, certfile=str(certs.client_invalid))
    server = create_server_tls_context(certfile=str(certs.server_combined), ca_trust=ca)

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
