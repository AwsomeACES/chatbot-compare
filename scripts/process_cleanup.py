"""Release a UI fixture's entire server process tree before deleting its files."""

import os
import signal
import subprocess


def stop_process_tree(process: subprocess.Popen, timeout: float = 10) -> None:
    """Stop an owned fixture. POSIX callers must use start_new_session=True.

    Windows virtual-environment Python launchers can spawn the actual server as
    a child. Terminating only the launcher leaves that server holding SQLite.
    """
    if process.poll() is not None:
        return
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
        if result.returncode and process.poll() is None:
            raise RuntimeError("Could not stop the isolated UI server process tree.")
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            raise RuntimeError("Isolated UI server did not exit after tree termination.") from None
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=timeout)
