"""The page's own English and German translations (toEn / toDe in human-scoring.html), run in Node."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).parent.parent / "human_scoring" / "human-scoring.html"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js not installed")


def translate(texts: list[str]) -> dict[str, list[str]]:
    src = PAGE.read_text(encoding="utf-8")
    block = src[src.index("const EN = {"):src.index("function T(")]
    script = block + "\nconst texts = " + json.dumps(texts, ensure_ascii=False) + ";\n" \
        "process.stdout.write(JSON.stringify({en: texts.map(toEn), de: texts.map(toDe)}));\n"
    out = subprocess.run([NODE, "-"], input=script.encode("utf-8"), capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def test_daily_limit_says_tomorrow_in_every_language():
    src = PAGE.read_text(encoding="utf-8")
    assert "今天的提問次數已經用完，明天可以再問。" in re.search(r"function refreshAsk\(\)[\s\S]*?\n}", src).group(0)
    out = translate(["今天的提問次數已經用完，明天可以再問。", "今天已問了 10 題，請明天再來"])
    assert out["en"] == ["You've used all of today's questions. You can ask again tomorrow.",
                         "You have asked 10 today; please come back tomorrow"]
    assert out["de"] == ["Ihre Fragen für heute sind aufgebraucht. Morgen können Sie wieder fragen.",
                         "Sie haben heute 10 Fragen gestellt; bitte morgen wiederkommen"]


def test_questions_left_singular_and_plural():
    out = translate(["今天還可以問 1 題。", "今天還可以問 3 題。"])
    assert out["en"] == ["You can ask 1 more question today.", "You can ask 3 more questions today."]
    assert out["de"] == ["Heute können Sie noch eine Frage stellen.", "Heute können Sie noch 3 Fragen stellen."]


def test_share_words_in_every_language():
    words = ["分享", "已分享", "複製連結", "取消分享", "連結已複製", "由 TheoClaw 生成，僅供參考",
             "這個分享已取消，或者不存在。", "今天分享的次數已達上限，請明天再來"]
    out = translate(words)
    assert out["en"][:4] == ["Share", "Shared", "Copy link", "Stop sharing"]
    assert out["de"][:4] == ["Teilen", "Geteilt", "Link kopieren", "Nicht mehr teilen"]
    for lang in ("en", "de"):
        assert not any(re.search(r"[一-鿿]", t) for t in out[lang]), out[lang]
