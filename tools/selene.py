"""Run the pinned selene (Lua linter) over the repo's Lua, downloading it first.

The release zip is checked against its sha256 and unpacked into .tools/.
Configuration: selene.toml and the dcs.yml std at the repo root.

Usage:
    uv run python -m tools.selene [selene args]   (default: tools packages/lua)
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.31.0"
# selene-light: no Roblox standard library (nothing fetched at run time).
SHA256 = {
    "linux": "0580eed94b56e8b4bad3b1d6f5a4f9e1a9f5d88ae5bc511290c3cd33cc5e0360",
    "macos": "780cf678626f776cf7b75db82673994e9ec0660a9b3ec66fbb71d8a86a879a0a",
    "windows": "0b31e71beb46927997332be4171e035e6d880c61a72cc5787d8eb1fd3886497e",
}
URL = "https://github.com/Kampfkarren/selene/releases/download/{v}/selene-light-{v}-{os}.zip"

ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / ".tools" / f"selene-{VERSION}"
DEFAULT_PATHS = ["tools", "packages/lua"]


OS_NAMES = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}


def _os_name() -> str:
    system = platform.system()
    if system not in OS_NAMES:
        raise SystemExit(f"selene: no pinned release for {system}")
    return OS_NAMES[system]


def ensure_selene() -> Path:
    """Path to the pinned selene binary, downloaded and verified if missing."""
    os_name = _os_name()
    exe = TOOLS_DIR / ("selene.exe" if os_name == "windows" else "selene")
    if exe.is_file():
        return exe
    url = URL.format(v=VERSION, os=os_name)
    with urllib.request.urlopen(url, timeout=120) as response:
        data: bytes = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256[os_name]:
        raise SystemExit(f"selene: sha256 mismatch for {url}: {digest}")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        exe.write_bytes(zf.read(exe.name))
    exe.chmod(0o755)
    return exe


def main(argv: list[str]) -> int:
    exe = ensure_selene()
    args = argv or ["--display-style", "quiet", *DEFAULT_PATHS]
    return subprocess.run([os.fspath(exe), *args], cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
