"""Church traditions the assistant can answer from: each has its own compiled knowledge base
and its own stance in the prompts.

The reader picks one on the page (default Methodist). Methodist keeps Wesley's notes and the
Methodist-specific rules; the others answer from their own confessions and writers. The
Methodist texts stay word for word what they were before the other traditions were added.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Denomination:
    key: str            # methodist, lutheran, ...
    label: str          # the value the page sends and the server records (human_server.DENOMINATIONS)
    name: str           # 循道衛理, 路德宗, ...
    kb: str             # the compiled knowledge base, a folder in knowledge/
    corpus: str         # how the tool descriptions name the source texts
    figure: str         # whose words are quoted: 衛斯理, 路德與路德宗信條, ...
    sources: str        # the main texts, for the quoting rule
    query_example: str  # an English search for the rag tool description
    cite_example: str   # a source as a sermon reply writes it
    brief_zh: str       # the sermon research brief's heading
    brief_en: str
    brief_de: str
    wesley: bool = False  # Wesley's notes on the New Testament (the wesley tool group)


METHODIST = Denomination(
    key="methodist", label="循道衛理 Methodist", name="循道衛理", kb="methodist.en.deepseek-flash",
    corpus="衛理宗文獻", figure="衛斯理", sources="衛斯理的講道、日記和著作",
    query_example="perfect love sin involuntary transgression", cite_example="衛斯理註釋 路加福音 15:16",
    brief_zh="衛斯理與循道傳統研究摘要", brief_en="Wesley and Methodist tradition brief",
    brief_de="Wesley und die methodistische Tradition", wesley=True)

LUTHERAN = Denomination(
    key="lutheran", label="信義會 Lutheran", name="路德宗", kb="lutheran.en.deepseek-flash",
    corpus="路德宗文獻", figure="路德與路德宗信條",
    sources="《協同書》的信條（奧斯堡信條、辯護書、施馬加登信條、大小要理問答、協同信條）和路德的著作",
    query_example="real presence body blood sacrament", cite_example="奧斯堡信條 第四條",
    brief_zh="路德與路德宗傳統研究摘要", brief_en="Luther and Lutheran tradition brief",
    brief_de="Luther und die lutherische Tradition")

BAPTIST = Denomination(
    key="baptist", label="浸信會 Baptist", name="浸信會", kb="baptist.en.deepseek-flash",
    corpus="浸信會文獻", figure="浸信會信條與作者",
    sources="浸信會的信條（1689 年倫敦浸信會信條、基奇要理問答、新罕布什爾信條）和司布真、富勒等浸信會作者",
    query_example="baptism believers immersion ordinance", cite_example="1689 年倫敦浸信會信條 第 29 章",
    brief_zh="浸信會傳統研究摘要", brief_en="Baptist tradition brief", brief_de="Die baptistische Tradition")

ANGLICAN = Denomination(
    key="anglican", label="聖公會 Anglican", name="聖公會", kb="anglican.en.deepseek-flash",
    corpus="聖公會文獻", figure="聖公會信條與神學家",
    sources="《三十九條》、《講道集》（Homilies）、《公禱書》和胡克、朱厄爾等聖公會神學家",
    query_example="sacraments ordained of Christ two", cite_example="《三十九條》第 25 條",
    brief_zh="聖公會傳統研究摘要", brief_en="Anglican tradition brief", brief_de="Die anglikanische Tradition")

REFORMED = Denomination(
    key="reformed", label="長老會／改革宗 Presbyterian / Reformed", name="加爾文宗（改革宗）", kb="reformed.en.deepseek-flash",
    corpus="加爾文宗（改革宗）文獻", figure="改革宗信條與加爾文",
    sources="西敏信條與大小要理問答、海德堡要理問答、比利時信條、多特信經和加爾文的《基督教要義》",
    query_example="predestination election eternal decree", cite_example="西敏信條 第三章",
    brief_zh="加爾文宗傳統研究摘要", brief_en="Calvin and Reformed tradition brief",
    brief_de="Calvin und die reformierte Tradition")

DENOMS: dict[str, Denomination] = {d.key: d for d in (METHODIST, LUTHERAN, BAPTIST, ANGLICAN, REFORMED)}
DEFAULT = METHODIST


def get(ref: str | Denomination | None) -> Denomination:
    """By key or by the page's label; anything else (None, 無宗派, an old value) is Methodist."""
    if isinstance(ref, Denomination):
        return ref
    for d in DENOMS.values():
        if ref in (d.key, d.label):
            return d
    return DEFAULT
