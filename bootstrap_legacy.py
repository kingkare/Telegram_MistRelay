#!/usr/bin/env python3
"""One-shot, explicitly authorized import for pre-database installations."""

import sys

from legacy_config import legacy_yaml_bootstrap_enabled


def main() -> int:
    if not legacy_yaml_bootstrap_enabled():
        print(
            "legacy bootstrap refused: set MISTRELAY_ALLOW_LEGACY_YAML_BOOTSTRAP=1 "
            "only on this one-off command",
            file=sys.stderr,
        )
        return 1

    from db import ensure_default_admin, init_db

    init_db()
    ensure_default_admin()
    print("legacy configuration verified in SQLite and retired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
