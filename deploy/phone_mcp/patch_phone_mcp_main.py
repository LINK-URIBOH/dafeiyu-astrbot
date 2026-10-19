"""Patch PhoneMCP's main.py so its emoji banner cannot crash on GBK consoles.

The official Windows executable (v0.5.0 / v0.3.4) raises
``UnicodeEncodeError: 'gbk' codec can't encode character '\\u2705'`` while
printing the startup banner.  Running from source with stdout/stderr forced to
UTF-8 avoids the crash.

Usage:
    python patch_phone_mcp_main.py <path-to-phoneMcp-repo>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MARKER = "# --- phone-mcp UTF-8 stdout patch ---"
BLOCK = f"""
{MARKER}
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass
# --- end phone-mcp UTF-8 stdout patch ---
"""
NEEDLE = "import argparse\nimport sys\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", help="Path to the cloned phoneMcp repository")
    args = parser.parse_args()

    main_py = Path(args.repo) / "main.py"
    if not main_py.exists():
        print(f"main.py not found: {main_py}", file=sys.stderr)
        return 1

    text = main_py.read_text(encoding="utf-8")
    if MARKER in text:
        print("already patched")
        return 0
    if NEEDLE not in text:
        print("unexpected main.py structure; patch manually", file=sys.stderr)
        return 1

    main_py.write_text(text.replace(NEEDLE, NEEDLE + BLOCK, 1), encoding="utf-8")
    print(f"patched {main_py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
