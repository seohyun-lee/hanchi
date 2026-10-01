"""Probe the installed Kiwi: which POS tags it accepts, and how it analyzes reference inputs.

Usage: scripts/dev/probe_kiwi.sh   (prints a markdown report)
"""

from __future__ import annotations

import kiwipiepy
from kiwipiepy import Kiwi

CANDIDATE_TAGS = (
    "NNG NNP NNB NR NP VV VA VX VCP VCN MM MAG MAJ IC "
    "JKS JKC JKG JKO JKB JKV JKQ JX JC EP EF EC ETN ETM XPN XSN XSV XSA XSM XR "
    "SF SP SS SSO SSC SE SO SW SL SH SN SB UN "
    "W_URL W_EMAIL W_HASHTAG W_MENTION W_SERIAL W_EMOJI Z_CODA Z_SIOT "
    "USER0 USER1 USER2 USER3 USER4 VV-I VV-R VA-I VA-R VX-I VX-R XSA-I XSA-R XSV-I XSV-R"
).split()

REFERENCE_INPUTS = [
    "건강센터",
    "센터필드",
    "강남센터필드",
    "메가스터디학원 강남센터",
    "강남 센터",
    "강남구 건강센터",
    "강남 센터필드",
]
WITH_DICT_INPUTS = [
    "강남센터필드",
    "강남 센터필드",
    "강남 센타필드",
    "GS25역삼점",
    "스타벅스강남R점",
]
EXTRA_INPUTS = [
    "찾아줘",
    "강남역 카페 찾아줘",
    "나를 찾아줘",
    "지금 영업중인 식당 찾아줘",
    "강남 방탈출 찾아줘 왜 안나와",
    "방탈출 찾아줘 아니 강남",
    "아이폰 15 케이스 찾아줘",
    "연세365의원",
    "123젤라또",
    "GLE어학원 대치점",
    "젤라또 2개",
    "B2B마케팅",
]


def fmt(kiwi: Kiwi, text: str) -> str:
    return " ".join(f"{t.form}/{t.tag}" for t in kiwi.tokenize(text))


def main() -> None:
    print(f"# Kiwi probe (kiwipiepy {kiwipiepy.__version__})\n")
    accepted, rejected = [], []
    for i, tag in enumerate(CANDIDATE_TAGS):
        k = Kiwi()
        try:
            k.add_user_word(f"탐색어{i}", tag)
            accepted.append(tag)
        except Exception:
            rejected.append(tag)
    print("## Tags accepted by add_user_word\n")
    print(" ".join(accepted), "\n")
    print("## Tags rejected\n")
    print(" ".join(rejected) or "(none)", "\n")

    plain = Kiwi()
    print("## Without user dictionary\n\n```")
    for s in REFERENCE_INPUTS + EXTRA_INPUTS:
        print(f"{s:<28} -> {fmt(plain, s)}")
    print("```\n")

    k = Kiwi()
    k.add_user_word("센터필드", "NNP", 5.0)
    print("## With add_user_word('센터필드', 'NNP', 5.0)\n\n```")
    for s in WITH_DICT_INPUTS:
        print(f"{s:<28} -> {fmt(k, s)}")
    print("```\n")
    print(f"space('강남센터필드메가스터디학원') -> {plain.space('강남센터필드메가스터디학원')}")


if __name__ == "__main__":
    main()
