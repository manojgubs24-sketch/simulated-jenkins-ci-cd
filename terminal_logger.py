import sys
import threading


_LOG_LOCK = threading.Lock()


def configure_terminal_output() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True, write_through=True)


def log(message: str) -> None:
    with _LOG_LOCK:
        print(message, flush=True)
