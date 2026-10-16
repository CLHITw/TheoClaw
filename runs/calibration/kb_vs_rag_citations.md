# Citations and unsupported statements, evaluator `deepseek-flash`

Citation check (ALCE-style citation precision): each sentence citing 「段落 N」 or 「第 N 頁」 against the cited passage.

| arm | answers | citations | judged | precision | not supported | label not found | section-only citations |
|---|---|---|---|---|---|---|---|
| kbvsrag-rag | 13 | 162 | 89 | 85% | 3 | 0 | 2 |
| kbvsrag-kb | 18 | 112 | 73 | 47% | 33 | 1 | 18 |
| kbvsrag-kbpdf | 16 | 128 | 81 | 70% | 17 | 0 | 4 |
| kbvsrag-hybrid | 12 | 118 | 69 | 91% | 2 | 0 | 7 |

Statements unsupported by the retrieved text, rechecked against the whole book (FActScore-style):

| arm | statements | supported by the book (not retrieved) | contradicted | not in the book |
|---|---|---|---|---|
| kbvsrag-rag | 30 | 1 (3%) | 1 (3%) | 28 (93%) |
| kbvsrag-kb | 31 | 4 (13%) | 0 (0%) | 27 (87%) |
| kbvsrag-kbpdf | 20 | 6 (30%) | 1 (5%) | 13 (65%) |
| kbvsrag-hybrid | 17 | 0 (0%) | 0 (0%) | 17 (100%) |
