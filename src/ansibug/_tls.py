# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import os.path
import pathlib
import ssl
import typing as t


def create_client_tls_context(
    verify: t.Literal["verify", "ignore"] | str = "verify",
    certfile: str | None = None,
    keyfile: str | None = None,
    password: str | None = None,
) -> ssl.SSLContext:
    """Creates a client TLS context.

    Creates a TLS context with the verification settings specified. The verify
    argument can be set to verify (default), ignore to ignore any verification
    settings, or a path to a file or directory containing the CA certs to use
    for the verification process.

    Args:
        verify: The verification settings for the TLS context.
        certfile: The path to the certificate and optional key used for the
            client's identity.
        keyfile: The path to the key if not present in the certfile path.
        password: The password used to decrypt the key if it is encrypted.
        ca_trust: Optional CA file that turns on client certificate
            authentication with a cert signed by a CA in this path.

    Returns:
        ssl.SSLContext: The configured client TLS context.

    Raises:
        ValueError: The verify location path does not exist.
    """
    ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    if verify == "ignore":
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.VerifyMode.CERT_NONE

    elif verify != "verify":
        _load_verify_locations(ssl_context, verify)

    if certfile:
        ssl_context.load_cert_chain(
            certfile,
            keyfile=keyfile,
            password=password,
        )

    return ssl_context


def create_server_tls_context(
    certfile: str,
    keyfile: str | None = None,
    password: str | None = None,
    ca_trust: str | None = None,
) -> ssl.SSLContext:
    """Creates a server TLS context.

    Creates a TLS context with the certificate settings specified. If no
    certfile is specified, the platforms defaults are used.

    Args:
        certfile: The path to the certificate and optional key used for the
            server's identity.
        keyfile: The path to the key if not present in the certfile path.
        password: The password used to decrypt the key if it is encrypted.
        ca_trust: Optional CA file that turns on client certificate
            authentication with a cert signed by a CA in this path.

    Returns:
        ssl.SSLContext: The configured server TLS context.
    """
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(
        certfile,
        keyfile=keyfile,
        password=password,
    )

    if ca_trust:
        ssl_context.verify_mode = ssl.VerifyMode.CERT_REQUIRED
        _load_verify_locations(ssl_context, ca_trust)

    return ssl_context


def _load_verify_locations(
    ssl_context: ssl.SSLContext,
    location: str,
) -> None:
    ca_path = pathlib.Path(os.path.expanduser(os.path.expandvars(location)))

    if ca_path.is_dir():
        ssl_context.load_verify_locations(capath=str(ca_path.absolute()))

    elif ca_path.exists():
        ssl_context.load_verify_locations(cafile=str(ca_path.absolute()))

    else:
        raise ValueError(f"Certificate CA verify path '{location}' does not exist")
