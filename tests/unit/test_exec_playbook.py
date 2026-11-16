# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import subprocess
import sys
import typing as t

import pytest

from ansibug._exec_playbook import _configure_ansible_env


def test_config_dump_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ANSIBLE_FORKS", "invalid")

    with pytest.raises(SystemExit) as e:
        _configure_ansible_env()

    assert e.value.code != 0
    stderr = capsys.readouterr().err
    assert "DEFAULT_FORKS" in stderr
    assert f"ansibug: failed to get Ansible config, '{sys.executable} -m ansible config dump --format json'" in stderr
    assert f"exited with rc {e.value.code}" in stderr


def test_config_dump_with_ansible_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ANSIBLE_DEBUG writes debug lines to stdout which breaks the json parsing.
    monkeypatch.setenv("ANSIBLE_DEBUG", "True")

    env = _configure_ansible_env()

    assert "ansibug.dap.debug" in env["ANSIBLE_CALLBACKS_ENABLED"]


@pytest.mark.parametrize(
    "isatty, env, expected",
    [
        (True, {}, True),
        (False, {}, False),
        (True, {"ANSIBLE_NOCOLOR": "1"}, False),
        (True, {"NO_COLOR": "1"}, False),
    ],
)
def test_config_dump_force_color(
    isatty: bool,
    env: dict[str, str],
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANSIBLE_FORCE_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("ANSIBLE_NOCOLOR", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: isatty)

    run_env: dict[str, str] = {}

    def run(args: list[str], **kwargs: t.Any) -> subprocess.CompletedProcess[str]:
        run_env.update(kwargs["env"])
        return subprocess.CompletedProcess(args, 0, stdout="[]", stderr="")

    monkeypatch.setattr(subprocess, "run", run)

    _configure_ansible_env()

    assert ("ANSIBLE_FORCE_COLOR" in run_env) is expected
    assert ("FORCE_COLOR" in run_env) is expected
