# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import atexit
import json
import os
import pathlib
import subprocess
import sys
import typing as t

from ._logging import LogLevel


def exec_playbook_connect(
    playbook_args: list[str],
    addr: str,
    *,
    no_wait: bool = True,
    log_file: pathlib.Path | None = None,
    log_level: LogLevel = "info",
) -> None:
    """Launch a new debug ansible-playbook process in connect mode.

    Execs a new ansible-playbook process that will connect to the debug server
    address listed. This will use the os.exec method to start the new process
    to replace the existing one with the env vars needed for ansibug to work.

    If use_tls is set to True the client will wrap the socket connection in a
    TLS tunnel to encrypt the data exchanged. By default it will attempt to
    verify the server's identity through its certificate. The kwarg tls_cert_ca
    can be set to a boolean that turns the verification process on or off. It
    can also be set to a string value that is the path to a CA file or CA
    directory of PEM files to use as the CA trust store(s).

    Args:
        playbook_args: Arguments to invoke ansible-playbook with.
        addr: The address to connect to.
        no_wait: Do not wait until the client has communicated with the
            ansible-playbook process and sent the configurationDone request
            before starting the playbook.
        log_file: Set ansibug debuggee logger to log to the absolute path of
            this file if set.
        log_level: Set ansibug debuggee logger filter to use this level when
            logging. This only applies if log_file is also set.
    """
    _exec_playbook(
        playbook_args=playbook_args,
        mode="connect",
        mode_env={},
        addr=addr,
        no_wait=no_wait,
        use_tls=False,
        log_file=log_file,
        log_level=log_level,
    )


def exec_playbook_listen(
    playbook_args: list[str],
    addr: str,
    *,
    no_wait: bool = True,
    use_tls: bool = False,
    tls_cert: pathlib.Path | None = None,
    tls_key: pathlib.Path | None = None,
    tls_password: str | None = None,
    tls_client_ca: pathlib.Path | None = None,
    log_file: pathlib.Path | None = None,
    log_level: LogLevel = "info",
) -> None:
    """Launch a new debug ansible-playbook process in listen mode.

    Execs a new ansible-playbook process that will listen for the debug server
    to connect to it. If no addr is specified, the port is provided by the OS.
    This will use the os.exec method to start the new process to replace the
    existing one with the env vars needed for ansibug to work.

    If use_tls is set to True the ansible-playbook process will wrap the socket
    connection in a TLS tunnel to encrypt the data exchanged. It will use the
    existing OS CA settings when attempting to create the TLS server endpoint
    but the tls_cert, tls_key, and tls_password kwargs can be used to provide
    a custom certificate and key. The tls_cert file can contain both the
    certificate and key, if they are in separate files use the tls_key kwarg
    to specify the key path.

    Args:
        playbook_args: Arguments to invoke ansible-playbook with.
        addr: The address to listen on.
        no_wait: Do not wait until the client has communicated with the
            ansible-playbook process and sent the configurationDone request
            before starting the playbook.
        use_tls: New process will wrap the socket connection through a TLS
            tunnel.
        tls_cert: The path to the TLS certificate PEM encoded file to use for
            TLS.
        tls_key: The path to the TLS key PEM encoded file to use for TLS.
        tls_password: The password for the tls_key if it is encrypted.
        tls_client_ca: Optional CA bundle that will enforce TLS client
            authentication with a cert signed by a CA in the bundle.
        log_file: Set ansibug debuggee logger to log to the absolute path of
            this file if set.
        log_level: Set ansibug debuggee logger filter to use this level when
            logging. This only applies if log_file is also set.
    """
    mode_env = {}

    if tls_cert:
        mode_env["ANSIBUG_TLS_SERVER_CERTFILE"] = str(tls_cert.absolute())

    if tls_key:
        mode_env["ANSIBUG_TLS_SERVER_KEYFILE"] = str(tls_key.absolute())

    if tls_password:
        # FUTURE: Find a better way to share this
        mode_env["ANSIBUG_TLS_SERVER_KEY_PASSWORD"] = tls_password

    if tls_client_ca:
        mode_env["ANSIBUG_TLS_CLIENT_CA"] = str(tls_client_ca.absolute())

    _exec_playbook(
        playbook_args=playbook_args,
        mode="listen",
        mode_env=mode_env,
        addr=addr,
        no_wait=no_wait,
        use_tls=use_tls,
        log_file=log_file,
        log_level=log_level,
    )


def _exec_playbook(
    playbook_args: list[str],
    mode: t.Literal["connect", "listen"],
    mode_env: dict[str, str],
    addr: str,
    *,
    no_wait: bool = True,
    use_tls: bool = False,
    log_file: pathlib.Path | None = None,
    log_level: LogLevel = "info",
) -> None:
    """Common launch code for connect and listen modes."""
    ansible_env = os.environ | mode_env | _configure_ansible_env()
    ansible_env["ANSIBUG_DEBUG_ADDR"] = addr
    ansible_env["ANSIBUG_MODE"] = mode
    ansible_env["ANSIBUG_NO_WAIT_FOR_CONFIG_DONE"] = str(no_wait).lower()
    ansible_env["ANSIBUG_USE_TLS"] = str(use_tls)

    if log_file:
        ansible_env["ANSIBUG_LOG_FILE"] = str(log_file.absolute())
        ansible_env["ANSIBUG_LOG_LEVEL"] = log_level

    argv = [sys.executable, "-m", "ansible", "playbook"] + playbook_args

    # Needed for coverage collection in testing to run the collectors before
    # execve is called.
    # https://github.com/nedbat/coveragepy/issues/43
    if "COVERAGE_RUN" in os.environ and hasattr(atexit, "_run_exitfuncs"):
        atexit._run_exitfuncs()

    os.execve(argv[0], argv, env=ansible_env)  # pragma: nocover


def _configure_ansible_env() -> dict[str, str]:
    """Builds the new ansibug enabled config options."""
    ansibug_path = pathlib.Path(__file__).parent.absolute()

    # Get the existing config options so we can safely prepend the ansibug
    # settings without clobbering the existing ones. This should reflect the
    # config the subsequent ansible-playbook call will use as it's run in the
    # same cwd with the same env vars.
    raw_config_dump = subprocess.run(
        [
            sys.executable,
            "-m",
            "ansible",
            "config",
            "dump",
            "--only-changed",
            "--format",
            "json",
        ],
        # Explicitly set verbosity so it doesn't display version info breaking
        # the json parsing.
        env=os.environ | {"ANSIBLE_VERBOSITY": "0"},
        capture_output=True,
        check=True,  # FUTURE: Maybe a nicer exception would be useful
    )
    config_dump = json.loads(raw_config_dump.stdout)

    enabled_callbacks = ["ansibug.dap.debug"]
    collections_path = [str(ansibug_path)]
    # FUTURE: Pass along the strategy used for ansibug to override.
    # strategy = "linear"

    to_check = {"CALLBACKS_ENABLED", "COLLECTIONS_PATHS"}
    for config_entry in config_dump:
        name = config_entry.get("name", None)
        if not name:
            continue

        if name == "CALLBACKS_ENABLED":
            to_check.remove("CALLBACKS_ENABLED")
            enabled_callbacks.extend(config_entry["value"])

        elif name == "COLLECTIONS_PATHS":
            to_check.remove("COLLECTIONS_PATHS")
            collections_path.extend(config_entry["value"])

        # elif name == "DEFAULT_STRATEGY":
        #     to_check.remove("DEFAULT_STRATEGY")
        #     strategy = config_entry["value"]

        if not to_check:
            break

    # Insert this module into the first PYTHONPATH so Ansible can import it.
    python_path = [e for e in os.environ.get("PYTHONPATH", "").split(os.pathsep) if e]
    python_path.insert(0, str(ansibug_path.parent))

    return {
        "ANSIBLE_CALLBACKS_ENABLED": ",".join(enabled_callbacks),
        "ANSIBLE_COLLECTIONS_PATH": os.pathsep.join(collections_path),
        "ANSIBLE_STRATEGY": "ansibug.dap.debug",
        "PYTHONPATH": os.pathsep.join(python_path),
    }
