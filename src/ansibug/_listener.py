# -*- coding: utf-8 -*-

# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations


def listen(
    hostname: str,
    port: int,
    wait_for_client: bool,
) -> None:
    print(f"Listening on {hostname}:{port}")
    a = ""
