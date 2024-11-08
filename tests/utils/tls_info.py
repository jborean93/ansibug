# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import datetime
import pathlib

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


@dataclasses.dataclass(frozen=True)
class CertFixture:
    ca: pathlib.Path
    password: str
    client_invalid: pathlib.Path
    client_combined: pathlib.Path
    client_cert_only: pathlib.Path
    client_key_encrypted: pathlib.Path
    client_key_plaintext: pathlib.Path
    server_combined: pathlib.Path
    server_cert_only: pathlib.Path
    server_key_plaintext: pathlib.Path
    server_key_encrypted: pathlib.Path


def generate_cert(
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
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()), critical=False)
    )
    if extensions:
        for ext, critical in extensions:
            builder = builder.add_extension(ext, critical)

    return builder.sign(sign_key, SHA256()), private_key


def serialize_cert(
    cert: x509.Certificate,
    key: types.CertificateIssuerPrivateKeyTypes,
    *,
    cert_only: pathlib.Path | None = None,
    combined: pathlib.Path | None = None,
    key_plaintext: pathlib.Path | None = None,
    key_encrypted: pathlib.Path | None = None,
    key_password: str | None = None,
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

    if key_encrypted and key_password:
        b_key_encrypted = key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=BestAvailableEncryption(key_password.encode()),
        )
        with open(key_encrypted, mode="wb") as fd:
            fd.write(b_key_encrypted)
