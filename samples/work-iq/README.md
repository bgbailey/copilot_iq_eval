# Contoso Work IQ Sample Seed Kit

This directory contains a 100% synthetic Microsoft 365 workplace grounding corpus (`@contoso.com`) backing `data/golden/contoso-work.yaml` (`W01`–`W22`). It exercises `cfeval` against unstructured M365 artifacts—OneDrive documents, SharePoint strategy decks, Teams meeting recaps, and Exchange escalation threads—without any customer or tenant-specific data.

## Contents

| Path | Simulated M365 Artifact | Cases Covered |
|---|---|---|
| `documents/fy25-pricing-committee-notes.md` | `FY25 Pricing Committee Notes.docx` (OneDrive) | `W01`–`W03`, `W09`, `W12`, `W15`, `W17`, `W19` |
| `documents/q3-board-prep-summary.md` | `Q3 Board Prep Deck.pptx` (SharePoint) | `W04`–`W06`, `W10`, `W18`, `W20` |
| `documents/emea-launch-sync-recap.md` | `EMEA Launch Sync Recap` (Teams meeting recap) | `W07`, `W13`, `W16`, `W22` (abstention check) |
| `documents/supply-chain-escalation-thread.md` | `Supply Chain Escalation Thread` (Exchange mail thread) | `W08`, `W11`, `W14` |
| `seed_manifest.json` | Machine-readable mapping from synthetic source files to M365 artifact names and golden IDs | `W01`–`W22` |
| `transcript_sample.jsonl` | Pre-captured 12-turn Work IQ transcript for zero-tenant scoring via `transcript-import` | `W01`–`W10`, `W19`, `W21` |

## Option A: Run Offline with Zero Tenant Setup

Score the bundled Work IQ sample transcript directly:

```powershell
python -m cfeval run --target transcript-import --transcript samples/work-iq/transcript_sample.jsonl --golden data/golden/contoso-work.yaml --no-publish
```

Or run the full 22-question Work IQ suite against the deterministic offline mock target:

```powershell
python -m cfeval run --mock --golden data/golden/contoso-work.yaml --no-publish
```

## Option B: Seed into a Demo M365 Tenant (`@contoso.com`)

To evaluate live Microsoft 365 Copilot Chat (`work-iq` surface) in an isolated test tenant:

1. Sign in as a dedicated test account (for example `eval.tester@contoso.com`) in your isolated evaluation tenant (`contoso.onmicrosoft.example`).
2. Convert or upload the four files in `documents/` according to `seed_manifest.json`:
   - Save `fy25-pricing-committee-notes.md` as `FY25 Pricing Committee Notes.docx` in the test user's OneDrive `Strategy/` folder.
   - Export `q3-board-prep-summary.md` into slides named `Q3 Board Prep Deck.pptx` in a SharePoint site accessible to `eval.tester@contoso.com`.
   - Post `emea-launch-sync-recap.md` as a Teams meeting recap / channel note titled `EMEA Launch Sync Recap`.
   - Send `supply-chain-escalation-thread.md` to `eval.tester@contoso.com` with subject `Supply Chain Escalation Thread`.
3. Allow 15–30 minutes for Microsoft Graph semantic indexing to complete before running:

   ```powershell
   python -m cfeval run --target copilot-chat --golden data/golden/contoso-work.yaml --no-publish
   ```

> **Note on Work IQ evidence tiers:** Work IQ turns return `citations-only` grounding evidence via Graph attributions (`webUrl` / display name) rather than Fabric KQL semantic-model query logs. See [Surfaces and Evidence Tiers](../../docs/concepts/surfaces-and-evidence.md).
