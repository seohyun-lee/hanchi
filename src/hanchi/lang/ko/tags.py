"""Kiwi (Sejong-based) tag table → coarse :class:`PosClass` + Korean names.

The table covers every tag kiwipiepy 0.24.0 accepts (checked by a test). Irregular
conjugation marks (``VV-I``, ``VA-R`` …) share the entry of their base tag.
"""

from __future__ import annotations

from hanchi.backend import PosClass, TagInfo

P = PosClass

_TABLE: dict[str, tuple[PosClass, str]] = {
    "NNG": (P.NOUN, "일반명사"),
    "NNP": (P.PROPN, "고유명사"),
    "NNB": (P.NOUN, "의존명사"),
    "NR": (P.NUM, "수사"),
    "NP": (P.PRON, "대명사"),
    "VV": (P.VERB, "동사"),
    "VA": (P.ADJ, "형용사"),
    "VX": (P.AUX, "보조용언"),
    "VCP": (P.COPULA, "긍정지정사"),
    "VCN": (P.COPULA, "부정지정사"),
    "MM": (P.DET, "관형사"),
    "MAG": (P.ADV, "일반부사"),
    "MAJ": (P.CONJ, "접속부사"),
    "IC": (P.INTJ, "감탄사"),
    "JKS": (P.PARTICLE, "주격조사"),
    "JKC": (P.PARTICLE, "보격조사"),
    "JKG": (P.PARTICLE, "관형격조사"),
    "JKO": (P.PARTICLE, "목적격조사"),
    "JKB": (P.PARTICLE, "부사격조사"),
    "JKV": (P.PARTICLE, "호격조사"),
    "JKQ": (P.PARTICLE, "인용격조사"),
    "JX": (P.PARTICLE, "보조사"),
    "JC": (P.PARTICLE, "접속조사"),
    "EP": (P.ENDING, "선어말어미"),
    "EF": (P.ENDING, "종결어미"),
    "EC": (P.ENDING, "연결어미"),
    "ETN": (P.ENDING, "명사형전성어미"),
    "ETM": (P.ENDING, "관형형전성어미"),
    "XPN": (P.AFFIX, "체언접두사"),
    "XSN": (P.AFFIX, "명사파생접미사"),
    "XSV": (P.AFFIX, "동사파생접미사"),
    "XSA": (P.AFFIX, "형용사파생접미사"),
    "XSM": (P.AFFIX, "부사파생접미사"),
    "XR": (P.ROOT, "어근"),
    "SF": (P.PUNCT, "종결부호"),
    "SP": (P.PUNCT, "구분부호"),
    "SS": (P.PUNCT, "인용부호·괄호"),
    "SSO": (P.PUNCT, "여는 괄호"),
    "SSC": (P.PUNCT, "닫는 괄호"),
    "SE": (P.PUNCT, "줄임표"),
    "SO": (P.PUNCT, "붙임표"),
    "SW": (P.SYMBOL, "기타 기호"),
    "SL": (P.FOREIGN, "알파벳"),
    "SH": (P.FOREIGN, "한자"),
    "SN": (P.NUMBER, "숫자"),
    "SB": (P.SYMBOL, "순서 있는 글머리"),
    "UN": (P.UNKNOWN, "분석 불능"),
    "W_URL": (P.SPECIAL, "URL"),
    "W_EMAIL": (P.SPECIAL, "이메일"),
    "W_HASHTAG": (P.SPECIAL, "해시태그"),
    "W_MENTION": (P.SPECIAL, "멘션"),
    "W_SERIAL": (P.SPECIAL, "일련번호"),
    "W_EMOJI": (P.SPECIAL, "이모지"),
    "Z_CODA": (P.AFFIX, "덧붙은 받침"),
    "Z_SIOT": (P.AFFIX, "사이시옷"),
    "USER0": (P.NOUN, "사용자 정의 0"),
    "USER1": (P.NOUN, "사용자 정의 1"),
    "USER2": (P.NOUN, "사용자 정의 2"),
    "USER3": (P.NOUN, "사용자 정의 3"),
    "USER4": (P.NOUN, "사용자 정의 4"),
}

KNOWN_TAGS = frozenset(_TABLE)


def base_tag(tag: str) -> str:
    """``"VV-I"`` → ``"VV"``; other tags unchanged."""
    return tag.split("-", 1)[0] if tag.endswith(("-I", "-R")) else tag


def tag_info(tag: str) -> TagInfo:
    entry = _TABLE.get(base_tag(tag))
    if entry is None:
        return TagInfo(tag, P.UNKNOWN, "미정의 태그")
    return TagInfo(tag, entry[0], entry[1])
