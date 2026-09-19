"""Embedded PostgreSQL for local development and tests.

Production runs on Supabase. Locally, nothing has to be installed: the first run downloads the same
PostgreSQL 17 build that `embedded-postgres` (Java) and `pgserver` (Python) ship, unpacks it under `data/pgbin/`,
and starts a private cluster in `data/pgdata/`. The schema in `supabase/migrations/` is applied to both, so the
API, the MCP server and the test-suite behave identically against either database.
"""
from __future__ import annotations

import io
import logging
import os
import platform
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("finmcp.devpg")

PG_VERSION = os.environ.get("FINMCP_PG_VERSION", "17.6.0")
MAVEN = "https://repo1.maven.org/maven2/io/zonky/test/postgres"
DEFAULT_PORT = int(os.environ.get("FINMCP_PG_PORT", "54329"))


def _artifact() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin":
        arch = "arm64v8" if machine in {"arm64", "aarch64"} else "amd64"
        return f"embedded-postgres-binaries-darwin-{arch}", "postgres-darwin-" + ("arm_64" if arch == "arm64v8" else "x86_64") + ".txz"
    if system == "linux":
        arch = "arm64v8" if machine in {"arm64", "aarch64"} else "amd64"
        return f"embedded-postgres-binaries-linux-{arch}", "postgres-linux-" + ("arm_64" if arch == "arm64v8" else "x86_64") + ".txz"
    if system == "windows":
        return "embedded-postgres-binaries-windows-amd64", "postgres-windows-x86_64.txz"
    raise RuntimeError(f"No embedded PostgreSQL build for {system}/{machine}; set FINMCP_DATABASE_URL to an existing server.")


def ensure_binaries(bin_root: Path, version: str = PG_VERSION) -> Path:
    """Download and unpack PostgreSQL once. Returns the directory that contains bin/ and lib/."""
    target = bin_root / f"pg-{version}"
    if (target / "bin" / "pg_ctl").exists() or (target / "bin" / "pg_ctl.exe").exists():
        return target
    artifact, member = _artifact()
    url = f"{MAVEN}/{artifact}/{version}/{artifact}-{version}.jar"
    log.info("Downloading PostgreSQL %s (%s)…", version, url)
    tmp = target.with_suffix(".partial")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 - fixed Maven Central host
        jar = resp.read()
    with zipfile.ZipFile(io.BytesIO(jar)) as zf:
        txz = zf.read(member)
    with tarfile.open(fileobj=io.BytesIO(txz), mode="r:xz") as tf:
        tf.extractall(tmp, filter="tar")
    tmp.rename(target)
    log.info("PostgreSQL %s ready at %s", version, target)
    return target


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


class Cluster:
    """One PostgreSQL data directory listening on a TCP port (no unix sockets: macOS caps their path length)."""

    def __init__(self, data_dir: Path, *, bin_root: Path, port: int | None = None, database: str = "finmcp"):
        self.data_dir = Path(data_dir)
        self.bin_root = Path(bin_root)
        self.port = port or DEFAULT_PORT
        self.database = database
        self._pg: Path | None = None

    @property
    def pg(self) -> Path:
        if self._pg is None:
            self._pg = ensure_binaries(self.bin_root)
        return self._pg

    def _bin(self, name: str) -> str:
        return str(self.pg / "bin" / name)

    @property
    def url(self) -> str:
        return f"postgresql://postgres@127.0.0.1:{self.port}/{self.database}"

    def initialised(self) -> bool:
        return (self.data_dir / "PG_VERSION").exists()

    def init(self) -> None:
        self.data_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([self._bin("initdb"), "-D", str(self.data_dir), "-U", "postgres", "--auth=trust", "-E", "UTF8", "--no-sync"],
                       check=True, capture_output=True)

    def running(self) -> bool:
        if not self.initialised():
            return False
        r = subprocess.run([self._bin("pg_ctl"), "-D", str(self.data_dir), "status"], capture_output=True)
        return r.returncode == 0

    def start(self, *, timeout: float = 30.0) -> None:
        if not self.initialised():
            self.init()
        if self.running():
            return
        if _port_open(self.port):
            raise RuntimeError(f"Port {self.port} is already in use; set FINMCP_PG_PORT to a free port.")
        opts = f"-p {self.port} -c listen_addresses=127.0.0.1 -c unix_socket_directories='' -c fsync=off -c full_page_writes=off"
        subprocess.run([self._bin("pg_ctl"), "-D", str(self.data_dir), "-o", opts, "-l", str(self.data_dir / "postgres.log"), "-w",
                        "-t", str(int(timeout)), "start"], check=True, capture_output=True)
        self._ensure_database()

    def stop(self) -> None:
        if self.initialised() and self.running():
            subprocess.run([self._bin("pg_ctl"), "-D", str(self.data_dir), "-m", "fast", "-w", "stop"], check=False, capture_output=True)

    def _ensure_database(self) -> None:
        import psycopg

        deadline = time.time() + 20
        while True:
            try:
                with psycopg.connect(f"postgresql://postgres@127.0.0.1:{self.port}/postgres", autocommit=True, connect_timeout=3) as conn:
                    exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (self.database,)).fetchone()
                    if not exists:
                        conn.execute(f'CREATE DATABASE "{self.database}"')
                return
            except psycopg.OperationalError:
                if time.time() > deadline:
                    raise
                time.sleep(0.25)

    def destroy(self) -> None:
        self.stop()
        if self.data_dir.exists():
            shutil.rmtree(self.data_dir)


def dev_cluster(root: Path, *, port: int | None = None) -> Cluster:
    """The shared local cluster under data/ (used by `make api`, `make server`, the CLI)."""
    return Cluster(root / "data" / "pgdata", bin_root=root / "data" / "pgbin", port=port)


def temp_cluster(root: Path, tmp_dir: Path) -> Cluster:
    """A throwaway cluster on a random port (tests). Binaries are shared with the dev cluster."""
    return Cluster(Path(tmp_dir) / "pgdata", bin_root=root / "data" / "pgbin", port=_free_port(), database="finmcp_test")
