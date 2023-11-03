# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import argparse
import dataclasses
import shlex
import typing as t
from typing import IO


class ReturnErrorMessage(Exception):
    ...


class ErrorCapturingParser(argparse.ArgumentParser):
    def error(self, message: str) -> t.NoReturn:
        raise ReturnErrorMessage(message)

    def print_help(self, file: IO[str] | None = None) -> None:
        raise ReturnErrorMessage(self.format_help())


@dataclasses.dataclass(frozen=True)
class ReplCommand:
    command: t.Literal["remove_option", "set_option", "set_hostvar", "template"]


@dataclasses.dataclass(frozen=True)
class TemplateCommand(ReplCommand):
    expression: str


@dataclasses.dataclass(frozen=True)
class RemoveVarCommand(ReplCommand):
    name: str


@dataclasses.dataclass(frozen=True)
class SetVarCommand(ReplCommand):
    name: str
    expression: str


def parse_repl_args(
    args: str,
) -> ReplCommand | str:
    """Parses an ansibug repl console command.

    Parses the raw command from the ansibug repl evaluation request. It uses
    argparse to parse the string value into a known command and their arguments
    otherwise it returns a string to send back to the client.

    Args:
        args: The raw string to parse.

    Returns:
        ReplCommand | str: The ReplCommand instance if it's a valid command,
        otherwise the string to display back to the client.
    """
    aliases = {
        "remove_option": ["ro"],
        "set_option": ["so"],
        "set_hostvar": ["sh"],
        "template": ["t"],
    }

    parser = ErrorCapturingParser(
        prog="!",
        description="Ansibug debug console repl commands",
    )

    command_parser = parser.add_subparsers(
        dest="command",
        required=True,
        help="The command to run",
    )

    remove_option = command_parser.add_parser(
        "remove_option",
        aliases=["ro"],
        description="Removes the option specified from the current module options.",
        help="Remove a module option.",
    )
    remove_option.add_argument(
        "name",
        help="The name of the option to remove.",
    )

    set_option = command_parser.add_parser(
        "set_option",
        aliases=["so"],
        description="Adds or sets the provided option for the current module options using the expression provided.",
        help="Set a module option.",
    )
    set_option.add_argument(
        "name",
        help="The name of the option to add/set.",
    )

    set_hostvar = command_parser.add_parser(
        "set_hostvar",
        aliases=["sh"],
        description="Adds or sets the provided variable for the current host using the expression provided.",
        help="Set a host variable.",
    )
    set_hostvar.add_argument(
        "name",
        help="The name of the hostvar to add/set.",
    )

    command_parser.add_parser(
        "template",
        aliases=["t"],
        description="Templates the expression provided after the command and returns the result. The expression "
        "provided should not be wrapped in {{ ... }} as the value is already treated as an expression.",
        help="Template an expression",
    )

    # The provided value from the repl is just a string, we need to convert it
    # to a command line and parse the known args. We only do the known args
    # because some commands need the raw value provided outside of a cmd split
    # processing argparse uses.
    split_args = shlex.split(args)

    try:
        parsed_args = parser.parse_known_args(split_args)[0]
    except ReturnErrorMessage as e:
        return str(e)

    command = str(parsed_args.command)
    if command not in aliases:
        # Need to resolve the alias back to the expected command name.
        for final, cmd_aliases in aliases.items():  # pragma: nocover
            for a in cmd_aliases:
                if command == a:
                    parsed_args.command = final
                    break

            if command != parsed_args.command:
                break

    if parsed_args.command == "template":
        # The value after the command needs to be extracted.
        expr = args[args.index(command) + len(command) :].lstrip()

        return TemplateCommand(command="template", expression=expr)

    elif parsed_args.command in ["set_option", "set_hostvar"]:
        # The value after the option/var name needs to be extracted.
        remaining = args[args.index(command) + len(command) :].lstrip()
        remaining = remaining[remaining.index(parsed_args.name) + len(parsed_args.name) :]
        if remaining.startswith('"') or remaining.startswith("'"):
            remaining = remaining[1:]

        expr = remaining.lstrip()

        return SetVarCommand(parsed_args.command, parsed_args.name, expr)

    else:
        return RemoveVarCommand(parsed_args.command, parsed_args.name)
