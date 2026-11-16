# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

from ansibug.ansible_collections.ansibug.dap.plugins.plugin_utils._repl_util import (
    RemoveVarCommand,
    SetVarCommand,
    parse_repl_args,
)


def test_unbalanced_quotes() -> None:
    actual = parse_repl_args("so name 'value")

    assert isinstance(actual, str)
    assert actual.startswith("Failed to parse repl command:")


def test_alias_resolved() -> None:
    assert parse_repl_args("so name 'value'") == SetVarCommand(command="set_option", name="name", expression="'value'")
    assert parse_repl_args("ro name") == RemoveVarCommand(command="remove_option", name="name")
