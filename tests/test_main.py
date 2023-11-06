# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import argparse

import pytest

from ansibug.__main__ import _parse_addr


@pytest.mark.parametrize(
    ["value", "expected"],
    [
        ("localhost:0", ("localhost", 0)),
        ("[localhost]:0", ("localhost", 0)),
        ("0", ("localhost", 0)),
        ("192.168.1.1:1234", ("192.168.1.1", 1234)),
        ("[192.168.1.1]:564", ("192.168.1.1", 564)),
        ("[2001:db8::1]:22", ("2001:db8::1", 22)),
    ],
)
def test_parse_addr(value: str, expected: tuple[str, int]) -> None:
    actual = _parse_addr(value)

    assert actual == expected


@pytest.mark.parametrize("value", ["localhost", "2001:db8::1:22f8"])
def test_parse_addr_fail(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="listener must be in the format \\[host:\\]port"):
        _parse_addr(value)
