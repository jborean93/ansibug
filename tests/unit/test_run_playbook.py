# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import importlib.metadata
import pathlib

import pytest

from ansibug._run_playbook import _ansible_playbook_path


def test_ansible_playbook_path() -> None:
    # argv[0] is set to this so ssh can find the 'ansible' script next to it
    # for SSH_ASKPASS.
    actual = _ansible_playbook_path()
    assert actual is not None
    assert pathlib.Path(actual).with_name("ansible").is_file()


def test_ansible_playbook_path_no_ansible_core(monkeypatch: pytest.MonkeyPatch) -> None:
    def distribution(name: str) -> importlib.metadata.Distribution:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "distribution", distribution)
    assert _ansible_playbook_path() is None
