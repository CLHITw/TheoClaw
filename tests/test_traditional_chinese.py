"""All Chinese we wrote (prompts, tool descriptions, messages, tasks, configs, docs) must be 繁體.

Scripture text in data/ comes from the 和合本 as published and is not checked.
"""

from pathlib import Path

import pytest

from theoclaw.common import zh

ROOT = Path(__file__).resolve().parent.parent
FILES = [*ROOT.glob("theoclaw/**/*.py"), *ROOT.glob("theoclaw/**/*.md"), *ROOT.glob("graders/*.py"),
         *ROOT.glob("tasks/*.yaml"), *ROOT.glob("config/*.yaml"), *ROOT.glob("experiments/*.yaml"),
         *ROOT.glob("scripts/*.py"), *ROOT.glob("tests/*.py"), ROOT / "README.md",
         *ROOT.glob("human_scoring/*.py"), *ROOT.glob("human_scoring/*.html"),
         *ROOT.glob("human_scoring/deploy/*.py"), *ROOT.glob("human_scoring/deploy/*.sh"),
         *ROOT.glob("human_scoring/deploy/*.service")]
FILES = [p for p in FILES if p.name != "conftest.py"]  # its fixture text is 和合本 scripture, quoted as published


@pytest.mark.skipif(not zh.available(), reason="pip install opencc-python-reimplemented")
def test_no_simplified_characters():
    problems = []
    for path in FILES:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            bad = zh.simplified_chars(line)
            if bad:
                problems.append(f"{path.relative_to(ROOT)}:{lineno} {''.join(sorted(bad))} in {line.strip()[:60]}")
    assert not problems, "\n".join(problems)


def test_detector_flags_simplified():
    if not zh.available():
        pytest.skip("opencc not installed")
    simplified = "\u536b\u7406\u516c\u4f1a"  # the Simplified spelling of 衛理公會, escaped
    assert zh.simplified_chars(simplified) and not zh.simplified_chars("衛理公會")
    scripture = "神的愛就在此向我們顯明了。皇后在鄰里"  # Traditional; phrase-level s2t would still rewrite 明了
    assert not zh.simplified_chars(scripture) and zh.simplified_chars(scripture, phrases=True)


def test_variant_forms_used_by_the_cuv_are_not_flagged():
    if not zh.available() or not zh.traditional_reference():
        pytest.skip("opencc or data/cuv.json missing")
    assert not zh.simplified_chars("吃飯、一群人、山峰、襯托")  # s2t rewrites these, the 和合本 uses them
    jue = chr(0x89C9)  # the Simplified form of 覺, written as a code point so this file stays 繁體
    assert zh.simplified_chars("感" + jue) == {jue}
