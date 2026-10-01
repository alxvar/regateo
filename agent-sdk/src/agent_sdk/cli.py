"""`regateo-agent`: tools for a session building an agent, which work without the engine.

    regateo-agent check agents/<architecture>/<version>   the submission check (agent_sdk.check)
"""
from __future__ import annotations

import sys

from agent_sdk import check


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in ("check",):
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return check.main(args[1:])


if __name__ == "__main__":
    sys.exit(main())
