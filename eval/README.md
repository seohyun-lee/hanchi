# Public evaluation set

General-purpose cases across web/content, commerce, places, people and spoken requests.
Run with `scripts/eval.sh` (or `hanchi eval -c eval/hanchi.yaml`). CI fails when the
scores drop below `baseline.yaml`.

| file | content |
|---|---|
| `hanchi.yaml` | plugins and case files used for this evaluation |
| `plugin/` | a small public dictionary (titles, people, products, places, homonyms) |
| `cases.tsv` | `query ⇥ candidates(｜) ⇥ expected_top1(｜) ⇥ domain: note` |
| `cases.jsonl` | cases needing their own dictionary, structured candidates or context |
| `roles.tsv`, `roles.jsonl` | `query ⇥ span ⇥ expected role ⇥ note` (`none` = must stay unresolved) |
| `baseline.yaml` | minimum scores |

Your own evaluation set can live anywhere: copy `hanchi.yaml`, point it at your plugin
and case files, and run `hanchi eval -c /path/to/your/hanchi.yaml`.
