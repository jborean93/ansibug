# Copyright (c) 2025 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import datetime


def get_canonicalized_variable_type(
    variable: object,
) -> str:
    """Get the type of a variable.

    Canonicalizes the type of a variable to a string representation. This is
    designed to canonicalize the type used by Ansible internally into a more
    human friendly value.

    Args:
        variable: The variable to check.

    Returns:
        str: The type of the variable
    """
    if isinstance(variable, str):
        return "str"
    elif isinstance(variable, bool):
        return "bool"
    elif isinstance(variable, int):
        return "int"
    elif isinstance(variable, float):
        return "float"
    elif isinstance(variable, tuple):
        return "tuple"
    elif isinstance(variable, collections.abc.Mapping):
        return "dict"
    elif isinstance(variable, collections.abc.Sequence):
        return "list"
    else:
        return type(variable).__name__
