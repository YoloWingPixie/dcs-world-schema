"""Smoke-test dist/dcs-world-api.lua in LuaLS (lua-language-server).

The pinned release is downloaded into .tools/ and checked against its sha256,
like tools/selene.py. The fixtures in tools/luals/ are copied, with the API
file, into a scratch Lua 5.1 workspace:

* ``--check`` diagnostics (Information and up): a fixture line ending in
  ``--! <code> ...`` expects exactly those diagnostic codes, any other line
  (and the API file) none;
* the language server: ``--! complete <label>`` expects a completion item
  ``label`` at the line's ``$`` (removed from the copy), ``--! hover <text>``
  a hover there that contains ``text``.

Directives on one line are separated by ``;``.

Usage:
    uv run python -m tools.luals [API_LUA]   (default: dist/dcs-world-api.lua)
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

VERSION = "3.19.1"
ASSETS = {
    ("Linux", "x86_64"): (
        "linux-x64.tar.gz",
        "e9235d2d72ef55bc41cf8c99cda2ed64777682024b4bb81f5dea425060c5cbb8",
    ),
    ("Linux", "aarch64"): (
        "linux-arm64.tar.gz",
        "abd2572e8fc929dc838a81ffb8473c5bce0bf39bfe8edb4b120b3b623176ce83",
    ),
    ("Darwin", "x86_64"): (
        "darwin-x64.tar.gz",
        "eb373c159cbe556711d7cd316315de2dce969bfd54b31edb7eb9cab2937f2cca",
    ),
    ("Darwin", "arm64"): (
        "darwin-arm64.tar.gz",
        "0bc077f4447f076b4c92c14e9fd303f5b569eda2ec74b4dca2b55f75fae2e90c",
    ),
    ("Windows", "AMD64"): (
        "win32-x64.zip",
        "fdb9a59108cf62517813c97fa5549b0e16d1ef0688306bac728b08434db7e4cd",
    ),
}
URL = "https://github.com/LuaLS/lua-language-server/releases/download/{v}/lua-language-server-{v}-{asset}"

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / ".tools" / f"lua-language-server-{VERSION}"
FIXTURES = Path(__file__).resolve().parent / "luals"
DEFAULT_API = ROOT / "dist" / "dcs-world-api.lua"
API_NAME = "dcs-world-api.lua"
LUARC = {"runtime.version": "Lua 5.1", "workspace.checkThirdParty": False}
CURSOR = "$"
_MARK = re.compile(r"--!\s*(.*?)\s*$")
# How long the server may take to answer once its workspace has loaded.
READY_S = 60.0


def ensure_luals() -> Path:
    """Path to the pinned lua-language-server, downloaded and verified if missing."""
    key = (platform.system(), platform.machine())
    if key not in ASSETS:
        raise SystemExit(f"luals: no pinned release for {key}")
    asset, sha256 = ASSETS[key]
    exe = (
        TOOLS_DIR
        / "bin"
        / ("lua-language-server.exe" if key[0] == "Windows" else "lua-language-server")
    )
    if exe.is_file():
        return exe
    url = URL.format(v=VERSION, asset=asset)
    with urllib.request.urlopen(url, timeout=120) as response:
        data: bytes = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise SystemExit(f"luals: sha256 mismatch for {url}: {digest}")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if asset.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(TOOLS_DIR)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            tf.extractall(TOOLS_DIR, filter="data")
    exe.chmod(0o755)
    return exe


@dataclass
class Fixture:
    """A fixture's text (``$`` removed) and its expectations by 0-based line."""

    name: str
    text: str
    diagnostics: dict[int, list[str]] = field(default_factory=dict)
    probes: list[tuple[str, int, int, str]] = field(default_factory=list)


def load_fixture(path: Path) -> Fixture:
    fixture = Fixture(path.name, "")
    lines = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        mark = _MARK.search(line)
        col = line.find(CURSOR)
        for directive in mark.group(1).split(";") if mark else []:
            kind, _, arg = directive.strip().partition(" ")
            if kind not in ("complete", "hover"):
                fixture.diagnostics[i] = sorted(directive.split())
            elif mark is None or not 0 <= col < mark.start():
                raise SystemExit(f"{path.name}:{i + 1}: {kind} without a {CURSOR}")
            else:
                fixture.probes.append((kind, i, col, arg.strip()))
        if any(p[1] == i for p in fixture.probes):
            line = line[:col] + line[col + 1 :]
        lines.append(line)
    fixture.text = "\n".join(lines) + "\n"
    return fixture


def check_diagnostics(
    exe: Path, workspace: Path, fixtures: list[Fixture], log: Path
) -> list[str]:
    """``--check`` the workspace; each diagnostic that is not expected, and
    each expected one missing."""
    out = log / "check.json"
    # Exits 1 when it finds any diagnostic; the report says which.
    run = subprocess.run(
        [
            os.fspath(exe),
            "--check",
            os.fspath(workspace),
            "--checklevel=Information",
            "--check_format=json",
            f"--check_out_path={out}",
            f"--logpath={log}",
        ],
        check=False,
        capture_output=True,
    )
    if run.returncode not in (0, 1):
        raise SystemExit(f"luals --check failed: {run.stderr.decode(errors='replace')}")
    found: dict[tuple[str, int], list[str]] = {}
    report = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    for uri, diagnostics in report.items():
        name = uri.rsplit("/", 1)[-1]
        for d in diagnostics:
            line = d["range"]["start"]["line"]
            found.setdefault((name, line), []).append(d["code"])
            if name == API_NAME:
                print(f"  {name}:{line + 1}: {d['code']}: {d['message']}")
    problems = []
    expected = {
        (f.name, line): codes for f in fixtures for line, codes in f.diagnostics.items()
    }
    for key in sorted(set(found) | set(expected)):
        got, want = sorted(found.get(key, [])), expected.get(key, [])
        if got != want:
            problems.append(
                f"{key[0]}:{key[1] + 1}: diagnostics {got}, expected {want}"
            )
    return problems


class Server:
    """A minimal LSP client of the language server over stdio."""

    def __init__(self, exe: Path, workspace: Path, log: Path) -> None:
        self.proc = subprocess.Popen(
            [os.fspath(exe), f"--logpath={log}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.next_id = 0
        uri = workspace.as_uri()
        self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": uri,
                "workspaceFolders": [{"uri": uri, "name": workspace.name}],
                "capabilities": {},
            },
        )
        self.notify("initialized", {})

    def _pipes(self) -> tuple[IO[bytes], IO[bytes]]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        return self.proc.stdin, self.proc.stdout

    def notify(self, method: str, params: Any, msg_id: int | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if msg_id is not None:
            msg["id"] = msg_id
        self._send(msg)

    def _send(self, msg: dict[str, Any]) -> None:
        stdin, _ = self._pipes()
        body = json.dumps(msg).encode()
        stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        stdin.flush()

    def _receive(self) -> dict[str, Any]:
        _, stdout = self._pipes()
        length = 0
        while line := stdout.readline().strip():
            name, _, value = line.decode().partition(":")
            if name.lower() == "content-length":
                length = int(value)
        if not length:
            raise SystemExit("luals: the language server closed its output")
        msg: dict[str, Any] = json.loads(stdout.read(length))
        return msg

    def request(self, method: str, params: Any) -> Any:
        self.next_id += 1
        self.notify(method, params, self.next_id)
        while True:
            msg = self._receive()
            if "method" in msg and "id" in msg:  # a request of the server's
                self._send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
            elif msg.get("id") == self.next_id:
                return msg.get("result")

    def ready_request(self, method: str, params: Any) -> Any:
        """``request``, repeated while the server answers null (loading)."""
        deadline = time.monotonic() + READY_S
        while (result := self.request(method, params)) is None or (
            "Workspace loading" in json.dumps(result)
        ):
            if time.monotonic() > deadline:
                return None
            time.sleep(0.5)
        return result

    def close(self) -> None:
        self.request("shutdown", None)
        self.notify("exit", None)
        stdin, _ = self._pipes()
        stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def _hover_text(result: Any) -> str:
    contents = (result or {}).get("contents")
    if isinstance(contents, dict):
        return str(contents.get("value", ""))
    if isinstance(contents, list):
        return "\n".join(
            c if isinstance(c, str) else c.get("value", "") for c in contents
        )
    return str(contents or "")


def check_probes(
    exe: Path, workspace: Path, fixtures: list[Fixture], log: Path
) -> list[str]:
    """Each completion or hover expectation the server does not meet."""
    if not any(f.probes for f in fixtures):
        return []
    problems = []
    server = Server(exe, workspace, log)
    try:
        for f in fixtures:
            uri = (workspace / f.name).as_uri()
            doc = {"uri": uri, "languageId": "lua", "version": 1, "text": f.text}
            server.notify("textDocument/didOpen", {"textDocument": doc})
            for kind, line, col, want in f.probes:
                at = {
                    "textDocument": {"uri": uri},
                    "position": {"line": line, "character": col},
                }
                where = f"{f.name}:{line + 1}"
                if kind == "complete":
                    result = server.ready_request("textDocument/completion", at)
                    items = (
                        result.get("items", []) if isinstance(result, dict) else result
                    )
                    labels = [i["label"] for i in items or []]
                    if want not in labels:
                        problems.append(
                            f"{where}: no completion {want} in {labels[:20]}"
                        )
                else:
                    text = _hover_text(server.ready_request("textDocument/hover", at))
                    if want not in text:
                        problems.append(
                            f"{where}: hover lacks {want!r}: {text[:300]!r}"
                        )
    finally:
        server.close()
    return problems


def main(argv: list[str]) -> int:
    api = Path(argv[0]) if argv else DEFAULT_API
    if not api.is_file():
        raise SystemExit(f"luals: no {api} (run `task build:lua`)")
    exe = ensure_luals()
    fixtures = [load_fixture(p) for p in sorted(FIXTURES.glob("*.lua"))]
    with tempfile.TemporaryDirectory() as tmp:
        workspace, log = Path(tmp) / "workspace", Path(tmp) / "log"
        workspace.mkdir()
        (workspace / API_NAME).write_bytes(api.read_bytes())
        (workspace / ".luarc.json").write_text(json.dumps(LUARC), encoding="utf-8")
        for f in fixtures:
            (workspace / f.name).write_text(f.text, encoding="utf-8")
        problems = check_diagnostics(exe, workspace, fixtures, log)
        problems += check_probes(exe, workspace, fixtures, log)
    for p in problems:
        print(p)
    checks = sum(len(f.diagnostics) + len(f.probes) for f in fixtures)
    print(
        f"LuaLS {VERSION}: {len(fixtures)} fixtures, {checks} expectations, "
        f"{len(problems)} problems"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
