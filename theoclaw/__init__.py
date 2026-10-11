"""TheoClaw: a Bible-study agent for a Methodist fellowship, and the harness that measures it.

Modules
    theoclaw.agent        the agent: loop, system prompt, scripture tools
    theoclaw.kb.compile   compiles Methodist sources into an OpenKB wiki
    theoclaw.kb.query     reads a compiled wiki (the agent's kb tools)
    theoclaw.evals        test runs, graders, reports, cost comparison, human scoring
    theoclaw.llm          every model call's settings (config/llm.yaml), API clients, single completions
    theoclaw.common       shared: references, scripture data, prices, token counting
"""
