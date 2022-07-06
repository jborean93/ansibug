import logging
import pathlib
import sys
import typing as t

import debugpy

import ansibug._dap as dap

logging.basicConfig(
    filename=str(pathlib.Path(__file__).parent / "debug-stdio.log"),
    filemode="w",
    format="%(asctime)s | %(name)s | %(filename)s:%(lineno)s %(funcName)s() %(message)s",
    level=logging.DEBUG,
)
log = logging.getLogger("debug.log")


"""
Terms
    Client - vscode
    DAP - ansibug
    Debugee - ansible-playbook

Debug Scenarios

* Launch new playbook locally

    Starts DAP process which exchanges msgs through stdio to client
    DAP binds a new random socket
    Calls RunInTerminalRequest to spawn a new ansible-playbook process
        Sends the ansible-playbook command with the required env vars
        These env vars tell ansible-playbook to connect to the socket specified
    All subsequent communication is relayed from client to debugee through DAP

* Attach to local playbook process by pid

    Starts DAP process with PID passed in
    DAP binds a new random socket
    DAP scans /tmp for UDS with ANSIBUG-{pid}
    DAP connects to UDS and sends socket info
    All subsequent communication is relayed from client to debugee through DAP

* Attach to remote playbook process

    Starts DAP process with socket passed in
    DAP connects to socket
    All subsequent communication is relayed from client to debugee through DAP

The attach scenarios would need a helper that launches ansible-playbook. This
launch needs to expose 2 methods

* Launch with debug plugins enabled
* Above but also send socket info
"""


def main() -> None:
    log.info("starting")

    debugpy.listen(("localhost", 12535))
    debugpy.wait_for_client()
    stdin = sys.stdin.buffer.raw
    stdout = sys.stdout.buffer.raw
    adapter = dap.DebugAdapterServer()
    run = True

    while run:
        data = stdin.read(4096)
        log.debug("STDIN: %s", data.decode())
        adapter.receive_data(data)

        while msg := adapter.next_message():
            if isinstance(msg, dap.LaunchRequest):
                adapter.run_in_terminal_request(
                    kind="integrated",
                    cwd=str(pathlib.Path(__file__).parent),
                    args=[
                        "python",
                        "-m",
                        "ansibug",
                        "launch",
                        "--connect",
                        "5679",
                        "main.yml",
                        "-vv",
                    ],
                    title="Ansible Debug Terminal",
                )

            elif isinstance(msg, dap.DisconnectRequest):
                run = False

        if data := adapter.data_to_send():
            stdout.write(data)
            stdout.flush()

    log.info("ending")


if __name__ == "__main__":
    try:
        main()
    except:
        log.exception("Failure")
        raise
