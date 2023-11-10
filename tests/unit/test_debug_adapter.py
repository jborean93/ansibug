# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pytest

from ansibug import _debug_adapter as da


@pytest.mark.parametrize("use_tls", [False, True, None])
def test_attach_address_port_tls(
    use_tls: bool | None,
) -> None:
    args = {
        "address": "addr",
        "port": 1,
    }
    expected = False
    if use_tls is not None:
        expected = use_tls
        args["useTls"] = use_tls

    actual = da.AttachArguments.from_json(args)
    assert actual.get_connection_tuple() == ("addr", expected)


@pytest.mark.parametrize(
    ["value", "expected"],
    [
        ("integratedTerminal", "integrated"),
        ("externalTerminal", "external"),
        (None, "integrated"),
    ],
)
def test_launch_console(
    value: str | None,
    expected: str,
) -> None:
    args = {"playbook": "main.yml"}

    if value is not None:
        args["console"] = value

    actual = da.LaunchArguments.from_json(args)
    assert actual.console == expected


def test_launch_unknown_console() -> None:
    expected = "Unknown console value 'invalid' - expected "
    with pytest.raises(ValueError, match=expected):
        da.LaunchArguments.from_json(
            {
                "playbook": "main.yml",
                "console": "invalid",
            }
        )
