"""Knowledge bases compiled from the Methodist sources with OpenKB.

    theoclaw.kb.compile   builds knowledge/<name>/ (OpenKB's .openkb/, raw/, wiki/) plus build.json
    theoclaw.kb.query     reads a built wiki; these are the agent's kb tools
"""

MANIFEST = "build.json"  # written by kb.compile into knowledge/<name>/, read by kb.query and evals
