# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pytest

from ansibug.__main__ import parse_args


def test_listen_wrap_tls_requires_cert(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args(["listen", "--wrap-tls", "main.yml"])

    assert "--wrap-tls requires --tls-cert" in capsys.readouterr().err
