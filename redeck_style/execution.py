"""Request-scoped concurrency limits and monotonic stage timing."""

import errno
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


_REQUEST_LIMIT = ContextVar("redeck_request_limit", default=None)


@contextmanager
def request_scope(directory, limit=4):
    if type(limit) is not int or limit < 1:
        raise ValueError("Request limit must be a positive integer")
    token = _REQUEST_LIMIT.set((Path(directory), limit) if directory else None)
    try:
        yield
    finally:
        _REQUEST_LIMIT.reset(token)


def _lock(stream):
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def request_slot(timeout=600):
    settings = _REQUEST_LIMIT.get()
    started = time.monotonic()
    if not settings:
        yield 0.0
        return
    directory, limit = settings
    directory.mkdir(parents=True, exist_ok=True)
    while True:
        for index in range(limit):
            stream = (directory / f"slot_{index:03d}.lock").open("a+b")
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            try:
                _lock(stream)
            except OSError as error:
                stream.close()
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                continue
            try:
                yield time.monotonic() - started
            finally:
                stream.close()
            return
        if time.monotonic() - started >= timeout:
            raise TimeoutError("Timed out waiting for a shared model request slot")
        time.sleep(.025)


@contextmanager
def measure(timings, stage):
    started = time.monotonic()
    try:
        yield
    finally:
        timings[stage] = timings.get(stage, 0.0) + time.monotonic() - started
