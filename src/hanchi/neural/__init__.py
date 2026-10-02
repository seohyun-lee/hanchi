"""Learned term-importance backends (optional).

Importing this package never imports heavy dependencies; :class:`BgeM3Encoder` loads
``FlagEmbedding`` (``pip install "hanchi[neural]"``) only when constructed.
"""

from hanchi.neural.lexical import LexicalEncoder, LexicalWeighter

__all__ = ["LexicalEncoder", "LexicalWeighter"]
