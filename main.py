"""
Ostrich AI Desktop Agent
========================
Entrypoint connecting the closed-loop orchestrator and delegate agents.
"""

import sys
from modules.agents.orchestrator import Orchestrator


def main() -> None:
    orchestrator = Orchestrator()
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        orchestrator.run(query)
    else:
        orchestrator.start()


if __name__ == "__main__":
    main()
