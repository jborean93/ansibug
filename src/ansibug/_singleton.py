# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import typing as t


class Singleton(type):
    """Singleton used to ensure only instance of a class exists."""

    __instances: dict[type, object] = {}

    def __call__(
        cls,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> object:
        if cls not in cls.__instances:
            cls.__instances[cls] = super().__call__(*args, **kwargs)

        return cls.__instances[cls]
