"""Recover only transient source reads; no strategy, state reset or stale fills.

work-card-dd0a1084-730e-4e5c-9718-a9db566a3014. The frozen BookReader still
validates every row, file identity, cursor and chronology. Failed reads never
advance its cursor. The normal runner heartbeat continues protective handling.
"""
import os
from pathlib import Path
import sqlite3
import stat

from intraday_pair import receipts
from intraday_pair.source import canonical, NS

RETRYABLE = {sqlite3.SQLITE_CANTOPEN, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def append_event(path, value):
    """Separate append-only diagnostic file, never an account or source store."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.geteuid() or s.st_mode & 0o077 or s.st_nlink != 1:
            raise ValueError('private_io_diagnostic_required')
        raw = canonical(value)+b'\n'
        if os.write(fd, raw) != len(raw):
            raise OSError('incomplete_io_diagnostic_write')
        os.fsync(fd)
    finally:
        os.close(fd)


class RecoveringBookReader:
    """A closed WAL writer can briefly remove RO readers' required sidecars.

    Retry later, without sleeping the executor, on CANTOPEN/BUSY/LOCKED only.
    There is no immutable fallback, writable source, read timeout extension,
    skipped backlog or refreshed timestamp. Other faults retain the old denial.
    """
    def __init__(self, path, clock, record, factory=receipts.BookReader):
        self.path, self.clock, self.record, self.factory = Path(path), clock, record, factory
        self.reader = None
        self.identity = None
        self.retry_at = 0
        self.errors = 0
        self.state = 'STARTING'
        self.last_error = None
        self.last_success_ns = None

    @property
    def cursor(self):
        return self.reader.cursor

    @cursor.setter
    def cursor(self, value):
        self.reader.cursor = value

    def status(self):
        return dict(status=self.state, read_errors_since_start=self.errors,
                    last_error_code=self.last_error, last_success_ns=self.last_success_ns)

    def poll(self, limit=200):
        before = self.clock.sample()
        if before['monotonic_ns'] < self.retry_at:
            return None
        try:
            source = self.path.stat()
            identity = (source.st_dev, source.st_ino)
            if self.identity is None:
                self.identity = identity
            elif identity != self.identity:
                raise receipts.Denied('source_file_replaced')
            if self.reader is None:
                self.reader = self.factory(self.path, self.clock)
                if getattr(self.reader, 'identity', self.identity) != self.identity:
                    raise receipts.Denied('source_file_replaced')
            result = self.reader.poll(limit)
        except sqlite3.OperationalError as error:
            code = getattr(error, 'sqlite_errorcode', None)
            if type(code) is not int or (code & 255) not in RETRYABLE:
                raise
            self.errors += 1
            self.last_error = code
            self.retry_at = self.clock.sample()['monotonic_ns']+NS//4
            if self.state != 'WAITING_SOURCE':
                self.record(dict(event='BOOK_READ_WAIT', at_ns=before['utc_ns'],
                                 sqlite_errorcode=code, read_errors_since_start=self.errors))
            self.state = 'WAITING_SOURCE'
            return None
        after = self.clock.sample()
        if self.state == 'WAITING_SOURCE':
            self.record(dict(event='BOOK_READ_RECOVERED', at_ns=after['utc_ns'],
                             read_errors_since_start=self.errors))
        self.state = 'AVAILABLE'
        self.retry_at = 0
        self.last_success_ns = after['utc_ns']
        return result
