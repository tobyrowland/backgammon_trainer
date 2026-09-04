"""Client for a persistent GNU Backgammon process.

GNU Backgammon is the analysis engine serious players use, and it is
world-class -- far stronger than anything that could be written here, and
stronger than any language model.  It is the opponent *and* the judge; the
language model never evaluates a position, it only explains gnubg's numbers.

gnubg is driven through its embedded Python interpreter (``gnubg -p FILE``),
which runs a script and exits.  That script (``gnubg_server.py``) therefore
holds the serve loop, and speaks JSON over a unix socket -- not stdio, which
is full of board diagrams and move announcements.
"""

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "gnubg_server.py")

#: Debian and Ubuntu put gnubg in /usr/games, which is often off PATH.
SEARCH_PATH = ["/usr/games", "/usr/local/games", "/usr/bin", "/usr/local/bin",
               "/opt/homebrew/bin"]


class GnubgError(RuntimeError):
    """A command the engine refused (an illegal move, a bad command)."""


class GnubgUnavailable(RuntimeError):
    """gnubg is not installed."""


def find_gnubg():
    found = shutil.which("gnubg")
    if found:
        return found
    for directory in SEARCH_PATH:
        candidate = os.path.join(directory, "gnubg")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class GnubgSession:
    """A running gnubg, driven over a socket.

    Start-up loads the bearoff databases and takes a few seconds, so the
    process is kept alive for the whole match rather than respawned per
    call.
    """

    def __init__(self, binary=None, start_timeout=120.0, call_timeout=300.0):
        self.binary = binary or find_gnubg()
        if not self.binary:
            raise GnubgUnavailable(
                "GNU Backgammon not found. Install it:\n"
                "  Debian/Ubuntu:  sudo apt-get install gnubg\n"
                "  macOS:          brew install gnubg\n"
                "It is the engine that plays you and grades you; the coach "
                "cannot work without it."
            )
        self.start_timeout = start_timeout
        self.call_timeout = call_timeout
        self._proc = None
        self._sock = None
        self._file = None
        self._id = 0
        self._stderr = []
        self._tmpdir = None

    # ------------------------------------------------------------ lifecycle

    def start(self):
        if self._proc is not None:
            return self
        self._tmpdir = tempfile.mkdtemp(prefix="bgcoach-")
        sock_path = os.path.join(self._tmpdir, "engine.sock")
        env = dict(os.environ, BGCOACH_SOCKET=sock_path)
        self._proc = subprocess.Popen(
            [self.binary, "-t", "-q", "-r", "-p", SERVER],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        ready = threading.Event()

        def drain():
            # stderr must be drained continuously or a full pipe would wedge
            # the engine mid-match.
            for line in self._proc.stderr:
                if "BGCOACH_READY" in line:
                    ready.set()
                else:
                    self._stderr.append(line.rstrip())
                    del self._stderr[:-200]

        threading.Thread(target=drain, daemon=True).start()

        if not ready.wait(self.start_timeout):
            self.close()
            raise GnubgError("gnubg did not start within %.0fs. Last output:\n%s"
                             % (self.start_timeout, "\n".join(self._stderr[-15:])))

        deadline = time.time() + 30
        while True:
            try:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._sock.connect(sock_path)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.05)
        self._sock.settimeout(self.call_timeout)
        self._file = self._sock.makefile("rwb")
        return self

    def close(self):
        try:
            if self._file:
                try:
                    self._send({"id": -1, "method": "quit", "params": {}})
                except Exception:
                    pass
                self._file.close()
        finally:
            self._file = None
            if self._sock:
                self._sock.close()
                self._sock = None
            if self._proc:
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                self._proc = None
            if self._tmpdir and os.path.isdir(self._tmpdir):
                shutil.rmtree(self._tmpdir, ignore_errors=True)
                self._tmpdir = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()
        return False

    # ------------------------------------------------------------- protocol

    def _send(self, payload):
        self._file.write((json.dumps(payload) + "\n").encode("utf-8"))
        self._file.flush()

    def call(self, method, **params):
        if self._file is None:
            raise GnubgError("engine is not running")
        self._id += 1
        self._send({"id": self._id, "method": method, "params": params})
        line = self._file.readline()
        if not line:
            raise GnubgError("engine closed the connection. Last output:\n%s"
                             % "\n".join(self._stderr[-15:]))
        resp = json.loads(line.decode("utf-8"))
        if not resp.get("ok"):
            raise GnubgError(resp.get("error") or "unknown engine error")
        return resp.get("result")

    # -------------------------------------------------------------- actions

    def ping(self):
        return self.call("ping")

    def new_match(self, length=5, level="world_class", seed=None, jacoby=False):
        return self.call("new_match", length=length, level=level, seed=seed,
                         jacoby=jacoby)

    def state(self):
        return self.call("state")

    def roll(self):
        return self.call("roll")

    def hint(self):
        return self.call("hint")

    def move(self, notation):
        return self.call("move", notation=notation)

    def double(self):
        return self.call("double")

    def take(self):
        return self.call("take")

    def drop(self):
        return self.call("drop")

    def next_game(self):
        return self.call("next_game")

    def decode(self, position_ids):
        return self.call("decode", position_ids=list(position_ids))

    def match(self, analyse=True):
        return self.call("match", analyse=analyse)

    def save(self, path, fmt="mat"):
        return self.call("save", path=path, fmt=fmt)

    def load(self, path):
        return self.call("load", path=path)

    def command(self, cmd):
        return self.call("command", command=cmd)
