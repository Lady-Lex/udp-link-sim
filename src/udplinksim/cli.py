"""Main entrypoint: dispatches --engine BEFORE importing PySide6/Qt."""

from __future__ import annotations

import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # CRITICAL (M0): Engine-only dispatch strictly BEFORE any PySide6 / Qt import!
    if "--engine" in args:
        engine_args = [a for a in args if a != "--engine"]
        from .engine import run_engine_cli

        return run_engine_cli(engine_args)

    if "--version" in args:
        from . import APP_NAME, __version__

        print(f"{APP_NAME} {__version__}")
        return 0

    from .gui.app import run_gui

    return run_gui(args)


if __name__ == "__main__":
    raise SystemExit(main())
