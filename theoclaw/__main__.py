"""`python -m theoclaw` is the agent; the other modules have their own command lines:

    python -m theoclaw ask "..."                   the agent (theoclaw.agent)
    python -m theoclaw.kb.compile --help           compile Methodist sources into a wiki
    python -m theoclaw.kb.query --help             list, inspect and query compiled wikis
    python -m theoclaw.evals --help                run, grade, report, compare, human scoring
"""

from .agent.__main__ import main

if __name__ == "__main__":
    main()
