# Public Readiness Validation Checklist

Run every check below locally (100% offline, zero cloud credentials required) before opening a release pull request or tagging a public version of `copilot_iq_eval`.

## Automated Verification Commands

```powershell
# 1. Unit & integration test suite (scorers, targets, stats, reports, CLI)
pytest

# 2. Linter & static hygiene
ruff check src tests tools samples

# 3. Synthetic Contoso star-schema aggregate parity against data/golden/contoso.yaml
python samples/contoso/seed_contoso.py --verify

# 4. Reference documentation freshness (schema.py, config.py, cli.py, golden schema)
python tools/gen_reference_docs.py --check

# 5. Relative Markdown link integrity across README, TRANSPARENCY_FAQ, docs/, samples/, data/
python tools/check_docs_links.py

# 6. Public wording & synthetic-tenant hygiene (config/wording-denylist.txt)
python tools/check_public_wording.py

# 7. Bundled sample golden parity (src/cfeval/sample/contoso.yaml == data/golden/contoso.yaml)
python -c "from pathlib import Path; assert Path('data/golden/contoso.yaml').read_bytes() == Path('src/cfeval/sample/contoso.yaml').read_bytes()"

# 8. End-to-end offline quickstart smoke (untuned -> tuned -> HTML report -> paired compare)
python -m cfeval run --mock --mock-profile untuned --golden data/golden/contoso-smoke.yaml --run-id check-untuned --no-publish
python -m cfeval run --mock --mock-profile tuned   --golden data/golden/contoso-smoke.yaml --run-id check-tuned   --no-publish
python -m cfeval report --run-dir runs/check-tuned
python -m cfeval compare runs/check-untuned runs/check-tuned
```

## Documentation & Governance Gates

- [ ] `README.md` is `<= 150` lines, embeds `docs/architecture/simplified-architecture.svg`, and completes its 60-second offline quickstart without cloud credentials.
- [ ] [`TRANSPARENCY_FAQ.md`](../../TRANSPARENCY_FAQ.md) accurately reflects supported case types, routing evidence tiers, `pass@k` vs `pass^k`, and judge calibration requirements.
- [ ] All bundled golden sets (`contoso.yaml`, `contoso-smoke.yaml`, `contoso-work.yaml`) and sample kits (`samples/contoso/`, `samples/work-iq/`) use strictly synthetic `@contoso.com` / `.example` identifiers.
- [ ] Zero real tenant GUIDs, customer names, internal codenames, or secrets appear in tracked files or notebook outputs.
