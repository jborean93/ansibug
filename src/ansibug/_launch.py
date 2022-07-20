# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import typing as t


def launch(
    playbook_args: t.List[str],
    mode: t.Literal["connect", "listen"],
    addr: str,
    wait_for_client: bool = True,
    log_file: t.Optional[pathlib.Path] = None,
    log_level: t.Literal["info", "debug", "warning", "error"] = "info",
) -> int:
    """Launch a new debuggable ansible-playbook process.

    Launches a new ansible-playbook process that can be debugged by ansibug.
    This new process inherits the stdio of the current process allowing it to
    act as a simple stub that wraps the invocation with the env vars needed
    for ansibug to communicate with it.

    Args:
        playbook_args: Arguments to invoke ansible-playbook with.
        mode: The debugee connection mode; connect will connect to the addr
            specified while listen will bind the socket to the addr specified.
        addr: The address to connect or listen on.
        wait_for_client: Wait until the client has communicated with the
            ansible-playbook process and sent the configurationDone request
            before starting the playbook.
        log_file: Set ansibug debuggee logger to log to the absolute path of
            this file if set.
        log_level: Set ansibug debuggee logger filter to use this level when
            logging. This only applies if log_file is also set.

    Returns:
        int: The return code of the ansible-playbook process once finished.
    """
    ansibug_path = pathlib.Path(__file__).parent
    new_environ = os.environ.copy()
    new_environ["ANSIBUG_MODE"] = mode
    new_environ["ANSIBUG_SOCKET_ADDR"] = addr
    new_environ["ANSIBUG_WAIT_FOR_CLIENT"] = str(wait_for_client).lower()

    if log_file:
        new_environ["ANSIBUG_LOG_FILE"] = str(log_file.absolute())
        new_environ["ANSIBUG_LOG_LEVEL"] = log_level

    python_path = [e for e in new_environ.get("PYTHONPATH", "").split(os.pathsep) if e]
    python_path.insert(0, str(ansibug_path.parent))
    new_environ["PYTHONPATH"] = os.pathsep.join(python_path)

    # Env vars override settings in the ansible.cfg, figure out a better way
    # to inject our collection, callback, and strategy plugin
    collections_path = [e for e in new_environ.get("ANSIBLE_COLLECTIONS_PATHS", "").split(os.pathsep) if e]
    collections_path.insert(0, str(ansibug_path))
    new_environ["ANSIBLE_COLLECTIONS_PATHS"] = os.pathsep.join(collections_path)

    enabled_callbacks = [e for e in new_environ.get("ANSIBLE_CALLBACKS_ENABLED", "").split(",") if e]
    enabled_callbacks.insert(0, "ansibug.dap.debug")
    new_environ["ANSIBLE_CALLBACKS_ENABLED"] = ",".join(enabled_callbacks)

    new_environ["ANSIBLE_STRATEGY"] = "ansibug.dap.debug"

    return subprocess.Popen(
        ["ansible-playbook"] + playbook_args,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=new_environ,
    ).wait()
