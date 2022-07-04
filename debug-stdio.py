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


def main() -> None:
    log.info("starting")
    stdin = sys.stdin.buffer.raw
    stdout = sys.stdout.buffer.raw
    adapter = dap.DebugAdapterServer()

    while True:
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
                        "5679",
                        "main.yml",
                        "-vv",
                    ],
                    title="Ansible Debug Terminal",
                )

        if data := adapter.data_to_send():
            stdout.write(data)
            stdout.flush()

    log.info("ending")


if __name__ == "__main__":
    try:
        debugpy.listen(("localhost", 5678))
        debugpy.wait_for_client()
        main()
    except:
        log.exception("Failure")
        raise
