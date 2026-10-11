"""打包評分伺服器需要的檔案，準備上傳到 VPS（不含 .env 與 API 金鑰）。

    python human_scoring/deploy/pack.py            寫出 human_scoring/deploy/theoclaw-scoring.tar.gz

包含：theoclaw/ 程式、config/、data/（提問模式查經用）、human_scoring/（含 assignment.json）、
assignment.json 用到的 runs 資料夾（只取 traces.jsonl 與 config.json）、requirements-server.txt 與部署腳本。
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "theoclaw-scoring.tar.gz"
SKIP_DIRS = {"__pycache__", "_backup_原版", ".pytest_cache"}


def _add_tree(tar: tarfile.TarFile, folder: Path) -> None:
    for p in sorted(folder.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_file() and not SKIP_DIRS & set(rel.parts) and p.suffix not in (".pyc",) \
                and p.name != OUT.name and p.name != ".env":
            tar.add(p, arcname=f"theoclaw/{rel.as_posix()}")


def main() -> None:
    assignment = json.loads((ROOT / "human_scoring" / "assignment.json").read_text(encoding="utf-8"))
    run_dirs = sorted({e["run_dir"] for e in assignment["items"]})
    with tarfile.open(OUT, "w:gz") as tar:
        for name in ("theoclaw", "config", "data", "human_scoring"):
            _add_tree(tar, ROOT / name)
        for d in run_dirs:
            for f in ("traces.jsonl", "config.json"):
                p = ROOT / d / f
                if p.exists():
                    tar.add(p, arcname=f"theoclaw/{Path(d).as_posix()}/{f}")
        tar.add(Path(__file__).parent / "requirements-server.txt", arcname="theoclaw/requirements-server.txt")
    print(f"寫出 {OUT}（{OUT.stat().st_size / 1e6:.1f} MB），包含 {len(run_dirs)} 個 runs 資料夾；不含 .env")


if __name__ == "__main__":
    main()
