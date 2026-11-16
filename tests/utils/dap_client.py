# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import io
import json
import os
import pathlib
import queue
import signal
import subprocess
import sys
import threading
import time
import types
import typing as t

import ansibug.dap as dap
from ansibug._debuggee import get_pid_info_path

ResponseMessage = t.TypeVar("ResponseMessage", bound=dap.ProtocolMessage)

# Must stay below the pytest-timeout value (60s) so we fail with a normal
# exception and the Ansible output instead of pytest killing the worker.
MSG_TIMEOUT = 20.0
PROC_TIMEOUT = 20.0


def get_test_env() -> dict[str, str]:
    env = os.environ | {"PYDEVD_DISABLE_FILE_VALIDATION": "1"}

    # We don't want this var from the outside to interfer with our test
    env.pop("ANSIBLE_CALLBACKS_ENABLED", None)
    env.pop("ANSIBLE_COLLECTIONS_PATH", None)
    env.pop("ANSIBLE_COLLECTIONS_PATHS", None)

    return env


class DAPClient:
    def __init__(
        self,
        test_name: str,
        log_dir: pathlib.Path | None = None,
        temp_dir: pathlib.Path | None = None,
    ) -> None:
        self._client = dap.DebugAdapterConnection()
        self._log_dir = log_dir
        self._test_name = test_name

        proc_env = get_test_env()
        dap_args = [
            sys.executable,
            "-m",
            "ansibug",
            "dap",
        ]
        if log_dir:
            dap_args.extend(
                [
                    "--log-file",
                    str((log_dir / f"ansibug-{test_name}-dap.log").absolute()),
                    "--log-level",
                    "debug",
                ]
            )
        if temp_dir:
            dap_args.extend(
                [
                    "--temp-dir",
                    str(temp_dir.absolute()),
                ]
            )

        self._dap_proc = subprocess.Popen(
            dap_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=proc_env,
        )
        self._stdin = t.cast(io.BytesIO, self._dap_proc.stdin)
        self._stderr: bytes | None = None

        self._stdout_thread = threading.Thread(
            target=self._stdout_recv,
            args=(self._dap_proc.stdout,),
            name="DAPClient-stdout-recv",
        )
        self._stderr_thread = threading.Thread(
            target=self._stderr_recv,
            args=(self._dap_proc.stderr,),
            name="DAPClient-stderr-recv",
        )
        self._incoming_msg: queue.Queue[dap.ProtocolMessage | None] = queue.Queue()
        self._ansible_procs: list[AnsibleProcess] = []

    def __enter__(self) -> DAPClient:
        self._stdout_thread.start()
        self._stderr_thread.start()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None = None,
        exception_value: BaseException | None = None,
        traceback: types.TracebackType | None = None,
        **kwargs: t.Any,
    ) -> None:
        try:
            for proc in self._ansible_procs:
                proc.stop()
                # pytest only displays captured output for failed tests.
                print(proc.format_output())

        finally:
            if self._dap_proc.poll() is None:
                try:
                    self.send(dap.DisconnectRequest())
                    self._dap_proc.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    self._dap_proc.kill()
                    self._dap_proc.wait()

            t.cast(io.BytesIO, self._dap_proc.stdin).close()
            self._stdout_thread.join(timeout=5)
            self._stderr_thread.join(timeout=5)

    @t.overload
    def send(self, msg: dap.ProtocolMessage) -> None: ...

    @t.overload
    def send(self, msg: dap.ProtocolMessage, return_type: type[ResponseMessage]) -> ResponseMessage: ...

    def send(
        self,
        msg: dap.ProtocolMessage,
        return_type: type[ResponseMessage] | None = None,
    ) -> ResponseMessage | None:
        if (rc := self._dap_proc.poll()) is not None:
            stderr = self._stderr or b"Unknown error"
            raise Exception(f"DAP process has ended with {rc}: {stderr.decode()}")

        self._client.queue_msg(msg)
        self._stdin.write(self._client.data_to_send())

        if not return_type:
            return None

        resp = self.wait_for_message(return_type)
        if isinstance(resp, dap.Response):
            assert msg.seq == resp.request_seq

        return resp

    def wait_for_message(
        self,
        expected_type: type[ResponseMessage],
        timeout: float = MSG_TIMEOUT,
    ) -> ResponseMessage:
        deadline = time.monotonic() + timeout
        while True:
            try:
                msg = self._incoming_msg.get(timeout=1)
                break
            except queue.Empty:
                pass

            now = time.monotonic()
            if dead := [p for p in self._ansible_procs if p.poll() is not None]:
                # Give the DA server a few seconds to relay any final events
                # before failing fast on an Ansible crash.
                deadline = min(deadline, now + 5)

            if now > deadline:
                rcs = ", ".join(f"{p.pid}: rc {p.returncode}" for p in dead)
                ansible_info = f" (Ansible process exited - {rcs})" if dead else ""
                raise TimeoutError(f"Timed out waiting for {expected_type.__name__}{ansible_info}")

        if not msg:
            stderr = self._stderr or b"Unknown error"
            raise Exception(f"DAP process has ended with {self._dap_proc.poll()}: {stderr.decode()}")

        elif isinstance(msg, dap.ErrorResponse) and expected_type != dap.ErrorResponse:
            raise Exception(f"Received error response for {msg.command.value}: {msg.message}")

        elif not isinstance(msg, expected_type):
            raise Exception(f"Received unexpected response type {type(msg)} but expected {expected_type}: {msg}")

        return msg

    def attach(
        self,
        playbook: str | pathlib.Path,
        playbook_dir: str | pathlib.Path | None = None,
        playbook_args: list[str] | None = None,
        ansibug_args: list[str] | None = None,
        attach_options: dict[str, t.Any] | None = None,
        attach_by_address: bool = False,
    ) -> AnsibleProcess:
        proc_args = [sys.executable, "-m", "ansibug", "listen"]
        if ansibug_args:
            proc_args += ansibug_args

        if self._log_dir and "--log-file" not in proc_args:
            proc_args.extend(
                [
                    "--log-file",
                    str((self._log_dir / f"ansibug-{self._test_name}-debuggee.log").absolute()),
                    "--log-level",
                    "debug",
                ]
            )

        proc_args.append(str(playbook))
        if playbook_args:
            proc_args += playbook_args

        new_environment = get_test_env()
        proc = AnsibleProcess(proc_args, cwd=playbook_dir, env=new_environment)
        self._ansible_procs.append(proc)

        pid_path = get_pid_info_path(proc.pid)
        for _ in range(20):
            if pid_path.exists():
                break
            elif (rc := proc.poll()) is not None:
                stdout, stderr = proc.communicate()
                raise Exception(
                    f"Error when launching new ansible-playbook process\nRC: {rc}\nSTDOUT\n{stdout.decode()}\nSTDERR\n{stderr.decode()}"
                )

            time.sleep(1)
        else:
            raise Exception("timed out waiting for proc pid")

        if attach_by_address:
            proc_conn_data = json.loads(pid_path.read_text())
            proc_info = {"address": proc_conn_data["address"]}
        else:
            proc_info = {"processId": proc.pid}

        attach_arguments = (attach_options or {}) | proc_info
        if "connectTimeout" not in attach_arguments:
            # macOS in CI is quite slow, bump the timeout to 20
            attach_arguments["connectTimeout"] = 20.0

        self.send(dap.AttachRequest(arguments=attach_arguments))
        self.wait_for_message(dap.AttachResponse, timeout=attach_arguments["connectTimeout"] + MSG_TIMEOUT)
        self.wait_for_message(dap.InitializedEvent)

        return proc

    def launch(
        self,
        playbook: str | pathlib.Path,
        playbook_dir: str | pathlib.Path | None = None,
        playbook_args: list[str] | None = None,
        launch_options: dict[str, t.Any] | None = None,
        do_not_launch: bool = False,
        expected_terminated: bool = False,
        check_request: collections.abc.Callable[[dap.RunInTerminalRequest], None] | None = None,
    ) -> AnsibleProcess:
        launch_args: dict[str, t.Any] = (launch_options or {}) | {"playbook": str(playbook)}
        if playbook_args:
            launch_args["args"] = playbook_args
        if playbook_dir:
            launch_args["cwd"] = str(playbook_dir)

        if self._log_dir and "logFile" not in launch_args:
            launch_args["logFile"] = str((self._log_dir / f"ansibug-{self._test_name}-debuggee.log").absolute())
            launch_args["logLevel"] = "debug"

        if "connectTimeout" not in launch_args:
            # macOS in CI is quite slow, bump the timeout to 20
            launch_args["connectTimeout"] = 20.0

        # The LaunchResponse is only sent once the debuggee connects back.
        connect_timeout = launch_args["connectTimeout"] + MSG_TIMEOUT

        self.send(dap.LaunchRequest(arguments=launch_args))
        resp = self.wait_for_message(dap.RunInTerminalRequest)

        if check_request:
            check_request(resp)

        new_environment = get_test_env()
        if resp.env:
            new_environment = new_environment | {k: v or "" for k, v in resp.env.items()}

        if do_not_launch:
            # This is for a specific test that makes sure the timeout is honoured
            self.send(dap.RunInTerminalResponse(request_seq=resp.seq, process_id=1))
            self.wait_for_message(dap.LaunchResponse, timeout=connect_timeout)
            raise Exception("This should not happen")

        else:
            proc = AnsibleProcess(resp.args, cwd=resp.cwd, env=new_environment)
            self._ansible_procs.append(proc)
            self.send(dap.RunInTerminalResponse(request_seq=resp.seq, process_id=proc.pid))

            if expected_terminated:
                err = self.wait_for_message(dap.ErrorResponse, timeout=connect_timeout)
                assert err.command == dap.Command.LAUNCH
                assert "ansible-playbook process ended before it connected" in (err.message or "")
                self.wait_for_message(dap.TerminatedEvent)
                return proc

            else:
                self.wait_for_message(dap.LaunchResponse, timeout=connect_timeout)

        self.wait_for_message(dap.InitializedEvent)

        return proc

    def _stdout_recv(
        self,
        stdout: io.BytesIO,
    ) -> None:
        while True:
            data = stdout.read(4096)
            if not data:
                break

            self._client.receive_data(data)

            while msg := self._client.next_message():
                self._incoming_msg.put(msg)

        self._dap_proc.wait()
        self._incoming_msg.put(None)

    def _stderr_recv(
        self,
        stderr: io.BytesIO,
    ) -> None:
        self._stderr = stderr.read()


class AnsibleProcess:
    """Popen-like wrapper for the ansible-playbook process that cannot hang a test.

    The output pipes are drained by background threads so Ansible never blocks
    on a full pipe and any partial output is available when a test fails.
    """

    def __init__(
        self,
        args: list[str],
        cwd: str | pathlib.Path | None,
        env: dict[str, str],
    ) -> None:
        self._proc = subprocess.Popen(
            args,
            cwd=cwd or None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Own process group so signals also reach the Ansible workers.
            start_new_session=True,
        )
        self._stdout = bytearray()
        self._stderr = bytearray()
        self._threads = [
            threading.Thread(target=self._read, args=(self._proc.stdout, self._stdout), daemon=True),
            threading.Thread(target=self._read, args=(self._proc.stderr, self._stderr), daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    @property
    def pid(self) -> int:
        return self._proc.pid

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode

    def poll(self) -> int | None:
        return self._proc.poll()

    def communicate(self, timeout: float = PROC_TIMEOUT) -> tuple[bytes, bytes]:
        """Waits for the process to end, raises TimeoutExpired if it doesn't."""
        self._proc.wait(timeout=timeout)
        for thread in self._threads:
            # A grandchild outside the process group could keep the pipe open.
            thread.join(timeout=5)

        return bytes(self._stdout), bytes(self._stderr)

    def stop(self) -> None:
        """Ends the process, SIGINT first for a graceful exit then SIGKILL."""
        if self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGINT)
                self._proc.wait(timeout=5)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                pass

        try:
            # Also reaps any leftover workers in the group.
            os.killpg(self._proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

        try:
            self.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def format_output(self) -> str:
        return (
            f"Ansible process {self.pid} rc {self.returncode}\n"
            f"STDOUT:\n{self._stdout.decode(errors='replace')}\n"
            f"STDERR:\n{self._stderr.decode(errors='replace')}"
        )

    def _read(self, pipe: t.IO[bytes], buffer: bytearray) -> None:
        while data := os.read(pipe.fileno(), 65536):
            buffer += data
