"""Compile Methodist sources into an OpenKB wiki, recording what the compile cost.

    python -m theoclaw.kb.compile profiles
    python -m theoclaw.kb.compile build wesley-core --model qwen3.8-flash --language en --dry-run
    python -m theoclaw.kb.compile build wesley-core --model qwen3.8-flash --language en

The profiles (what to compile) are in config/kb_profiles.yaml; every source comes from
the Methodist folder. Results go to knowledge/<profile>.<language>.<model>/.
"""
