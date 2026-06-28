# skills/ — MANIFEST

Agent skills: self-contained playbooks an agent reads to perform a recurring
task (each subfolder is one skill with its own `SKILL.md`).

## How an agent EXECUTES this folder
- Not executed as code. To use a skill, READ its `SKILL.md` and follow the
  steps. Skills orchestrate the `./gpt` commands; they do not bypass them.

## How an agent CHANGES this folder
- One skill = one subfolder containing `SKILL.md` (plus any helper assets). Keep
  each skill focused and self-describing; commands inside must match the current
  `./gpt` CLI. No personal paths (enforced by `tests/test_repo_hygiene.py` for
  the published skills).
- When the CLI changes, update the affected `SKILL.md` so its runbook stays correct.

## Subfolders (each a skill)
- `project-reconstruction/` — run the full extract→cluster→bundle→summarize flow.
- `chatgpt-export-triage/` — triage a raw ChatGPT export before processing.
- `catalog-query/` — query the catalog (`list/search/show/ask`).
- `model-benchmark/` — run and read a model benchmark sweep.
- `publish-redaction/` — sanitize and publish to `published/`.
