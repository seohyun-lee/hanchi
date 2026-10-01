"""Language packs.

The core (roles, resolver, weighting, ranking, plugin loading, evaluation) is
language-neutral. Everything language-specific — the morphological backend,
normalization, function-word rules, request/command patterns, spacing variants —
lives in a language pack under ``hanchi.lang.<code>`` and is reached only through
the interfaces defined by the core.
"""
