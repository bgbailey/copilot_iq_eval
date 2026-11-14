## Work item

Closes #

## What changed

-

## How it was verified

- [ ] `ruff check src tests tools`
- [ ] `mypy src/cfeval`
- [ ] `python -m pytest -m "not live" -q`
- [ ] `python -m cfeval run --strict --mock --profile tuned --no-publish`
- [ ] `python tools/check_public_wording.py` and `python tools/check_docs_links.py`
- [ ] Generated files (`kql/setup.kql`, `app/overlay/src/eval/generated/contract.ts`, `app/connectors/evals/metadata.example.json`, `docs/reference/*.md`) verified up to date (`git diff --exit-code` clean)
- [ ] App: `npm --prefix app/standalone run typecheck`, `npm --prefix app/standalone test`, `npm --prefix app/standalone run build` (if `app/` or `schema.py` changed)
- [ ] Documentation and `CHANGELOG.md` updated, or not needed (state why)

Summary lines from the commands above:

```text

```

## Unverified live behaviour

List each assumption this change makes about a live service, with the location of its `TODO(verify-live)` and `@pytest.mark.live` test. Write `None` if there are none.

## Checklist

- [ ] No tenant IDs, workspace IDs, user names, secrets, or non-synthetic answers (`@contoso.com` only)
- [ ] Evidence integrity preserved: `ERROR` and `INCONCLUSIVE` cannot become `PASS`
- [ ] No test, release gate, or hygiene check was weakened
