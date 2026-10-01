# Hanchi (한치)

> Korean query understanding: per-word role & weight from context. When the next step is unclear, Hanchi keeps the possibilities open instead of guessing.

[한국어](README.md)

Hanchi is a query-analysis layer on top of the Kiwi morphological analyzer. It is not a document indexer: it takes the short inputs that reach search engines and voice assistants and, for each word, estimates its role in the query (entity, category, location, constraint, command, …) and its weight from context. Hanchi does not search by itself. When an interpretation is ambiguous, it returns every plausible reading with probabilities rather than committing to one.

> **Status:** pre-alpha. The English documentation will be expanded as features land.

## License

Apache-2.0. Requires `kiwipiepy>=0.24.0` (earlier releases were LGPL). See [NOTICE](NOTICE).
