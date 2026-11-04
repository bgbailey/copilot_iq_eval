# ADR-010: Evaluate joint Work IQ + Fabric IQ answers with seeded documents and a sixth evaluator

- **Status:** Accepted
- **Date:** 2026-11-03
- **Plan sections:** §2.1 (finding 13), §4.4, §5.2, §6 (T20, T21), §8 (S8, P1.9, P4.1), §9.6.1, §9.6.3, §9.7, §12, §13 (PLAN version 1.3)
- **Deciders:** Owner (Principal Solution Engineer)
- **Related:** ADR-011 (pending, spike S8) decides which surfaces run the joint cases.

## Context

The customer question this harness answers is "does Copilot use the right certified data?". Real business questions rarely need data alone: "did we hit our revenue target?" needs the actual from a certified semantic model **and** the target from an approved planning document. A demo that only tests data answers misses the case customers ask about most, and the one where a draft document is most tempting.

Three facts shape the design:

1. **Work IQ grounds answers in Microsoft 365 content, not in Power BI.** The Work IQ API documents OneDrive and SharePoint files as context, but no Power BI or Fabric source. Answers that combine data with files are documented for Microsoft 365 Copilot Chat itself, so we cannot assume a single API reaches both (S42–S44).
2. **New documents must be indexed before Copilot finds them**, and the semantic index publishes no service level for this.
3. **The checks already exist for the data side.** `value_match`, `routing_match`, `no_decoy` and `citation_match` prove the figure, the model and the absence of decoys. Only "the right document was cited" is new.

## Options considered

| Option | For | Against |
|---|---|---|
| A. Data-only cases (status quo) | Nothing to build | Misses the joint question; the draft decoy is only tested as a negative |
| B. Joint cases scored by the AI judge alone | No new code evaluator | The judge would need the expected document and figures, which breaks the expected-blind rule; not deterministic |
| **C. Seeded documents with facts in the golden set, plus one deterministic evaluator** | Every figure has one source of truth; deterministic; reuses the existing checks | Needs SharePoint sites, a content pack, an upload step and an indexing wait |

## Decision

Option C.

- **Content pack.** `workiq/content.yaml` holds the text of three synthetic documents (an approved revenue-targets memo, service-level objectives and the existing draft decoy) with `{fact}` placeholders. The figures live once, in `evals/golden/models.yaml` `documents.<key>.facts`. `scripts/build_workiq_documents.py` renders the `.docx` files and a unit test fails on any drift.
- **Calibrated data.** nb_01 scales FY2025 gross revenue by region and the FY2025 Sev1 mean time to resolve to exact totals, so the documents can state real comparisons: actual $12.84M against a $12.5M target, MTTR 7.2 hours against a 6-hour objective.
- **Permissions are part of the test.** Source documents live on a site the `noaccess` persona cannot read; the draft lives where everyone can. The content-pack check enforces it.
- **Golden set.** Cases carry `expect.work_sources` (documents that must be cited) and `expect.work_facts` (document figures the answer must state). Four joint cases: JNT-001 (company target), JNT-002 (East, RLS), JNT-003 (service objective), JNT-004 (`noaccess`: nothing may leak).
- **Evaluators.** A sixth code-based evaluator, `work_source_match`, passes when every work source is cited, attributed or named. `value_match` additionally requires each expected fact to be stated (presence, within tolerance). `no_decoy`, `routing_match` and `citation_match` are unchanged and still apply.
- **Seeding.** `evals deploy workiq` uploads the documents to the sites in `[workiq.sites]`; creating the sites and their membership stays manual (T20).
- **Agent.** The declarative agent adds `OneDriveAndSharePoint` scoped to the planning site (P4.1).

## Consequences

- The evaluation row gains `work_sources` and `expected_facts`; both backends run the new evaluator unchanged (ADR-009). `expected_facts` is judge-blind.
- A demo now needs the documents seeded about a day ahead (§13). Spike S8 measures the real delay.
- Which surfaces can pass the joint cases is an open question until S8 (ADR-011). Until then they are part of the golden set but not of the gate's critical set on any surface S8 has not confirmed.
- The content pack is synthetic and committed, so the public repository carries no customer content.

## Contracts updated

`work_iq_api`, `graph_sharepoint_files` and the `copilot_chat_api` contextual-files fields are added to `config/contracts.yaml` with status `documented`; spike S8 confirms them.
