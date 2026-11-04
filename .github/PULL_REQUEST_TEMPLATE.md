## Summary

<!-- What this pull request changes, in a sentence or two. -->

Closes #

**Plan sections:** <!-- e.g. §9.6.1 -->

## Checklist

- [ ] The acceptance criteria in the linked issue are met.
- [ ] Unit tests added or updated; `uv run ruff check && uv run mypy src && uv run pytest` pass.
- [ ] `uv run evals validate --strict` passes (if `evals/golden/` or `evals/evaluators/` changed).
- [ ] No answer is scored outside `evals/evaluators/`: checks live in the evaluators, which run unchanged on both backends, and evaluator changes have unit tests.
- [ ] Endpoints, scopes and field names come from `config/contracts.yaml`, not from memory.
- [ ] Docs updated if behaviour or contracts changed; a decision is recorded as an ADR in `docs/decisions/` if one was made.
- [ ] No secrets, token caches, tenant IDs, domains, user names, workspace or item IDs, or customer data.

## Evidence

<!-- How you verified the change: commands run and what they showed, run IDs, or screenshots of the scorecard. Sanitise everything. -->
