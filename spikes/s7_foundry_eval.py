"""Spike S7: does our Foundry project run the evaluation design end to end? (ADR-008, Foundry path only)

Uses the repository's own definitions, so the spike tests exactly what the harness will run:

1. registers every evaluator in evals/evaluators/evaluators.yaml in the project's catalog under its
   content-addressed name (copilot_evals.evaluation.definitions.catalog_name);
2. creates an eval from eval-definition.yaml (data_source_config and testing_criteria, with the
   {catalog:...}, {judge_deployment} and {file:...} placeholders filled in);
3. uploads the sample rows (evals/evaluators/samples/eval-items.jsonl) and starts a run with the
   expected-blind extraction step as its data source;
4. polls the run, then saves the run and every output item, and prints per-row scores next to the
   local backend's verdicts so the two paths can be compared.

    uv run python spikes/s7_foundry_eval.py

Answers the TODO(spike-S7) items in config/contracts.yaml `foundry_evaluations`: request shapes,
version pinning, how an errored row looks, threshold semantics, cost. Signs in as the operator
(az login) with Foundry User on the Foundry resource. Raw results go to spikes/out/s7/.
"""

import argparse
import time
from pathlib import Path
from typing import Any

from _common import ROOT, heading, operator_credential, save, settings, utc_now
from azure.ai.projects import AIProjectClient

from copilot_evals.evaluation.definitions import EvaluationDefinitions, catalog_name, load_definitions

EVALUATORS_DIR = ROOT / "evals" / "evaluators"
TERMINAL = {"completed", "failed", "canceled"}


def fill(value: Any, definitions: EvaluationDefinitions, substitutions: dict[str, str]) -> Any:
    """Replace whole-string placeholders: {catalog:key}, {file:path} and the names in ``substitutions``."""
    if isinstance(value, dict):
        return {key: fill(item, definitions, substitutions) for key, item in value.items()}
    if isinstance(value, list):
        return [fill(item, definitions, substitutions) for item in value]
    if isinstance(value, str) and value.startswith("{") and value.endswith("}") and not value.startswith("{{"):
        inner = value[1:-1]
        if inner.startswith("catalog:"):
            return catalog_name(definitions, inner.removeprefix("catalog:"))
        if inner.startswith("file:"):
            return definitions.resolve_file(value)
        return substitutions.get(inner, value)
    return value


def evaluator_version(key: str, definitions: EvaluationDefinitions) -> dict[str, Any]:
    """The catalog entry for one evaluator, in the shape config/contracts.yaml records (preview API)."""
    spec = definitions.evaluators[key]
    fields = spec.fields
    text = spec.source.read_text(encoding="utf-8")
    threshold = "pass_threshold" if spec.kind == "code" else "threshold"
    definition: dict[str, Any] = {
        "type": spec.kind,
        "code_text" if spec.kind == "code" else "prompt_text": text,
        "init_parameters": {
            "type": "object",
            "properties": {"deployment_name": {"type": "string"}, threshold: {"type": "number"}},
            "required": ["deployment_name", threshold],
        },
        "metrics": {key: fields.get("metric", {})},
    }
    if spec.kind == "code":
        definition["data_schema"] = definitions.definition["data_source_config"]["item_schema"]
    return {
        "display_name": fields.get("display_name", key),
        "description": fields.get("description", ""),
        "categories": fields.get("categories", []),
        "definition": definition,
        "metadata": {"repository_key": key},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--items", type=Path, default=EVALUATORS_DIR / "samples" / "eval-items.jsonl")
    parser.add_argument("--timeout", type=int, default=settings().foundry.run_timeout_s)
    args = parser.parse_args()

    config = settings()
    if not config.foundry.endpoint:
        raise SystemExit("set [foundry] endpoint in config/settings.toml (infra/azure/deploy.sh prints it)")
    definitions = load_definitions(EVALUATORS_DIR)
    stamp = f"{utc_now():%Y%m%d%H%M%S}"
    record: dict[str, Any] = {"registrations": {}}
    project = AIProjectClient(endpoint=config.foundry.endpoint, credential=operator_credential())
    openai = project.get_openai_client()

    heading("1. Register evaluators")
    for key in definitions.evaluators:
        name = catalog_name(definitions, key)
        try:
            version = evaluator_version(key, definitions)
            created = project.beta.evaluators.create_version(name=name, evaluator_version=version)
            record["registrations"][name] = getattr(created, "as_dict", lambda: str(created))()
            print(f"registered {name}")
        except Exception as error:  # noqa: BLE001 - the error text is the finding
            record["registrations"][name] = {"error": repr(error)}
            print(f"FAILED {name}: {error}")

    heading("2. Create the eval")
    substitutions = {"judge_deployment": config.foundry.judge_deployment}
    evaluation = openai.evals.create(
        name=f"{config.foundry.eval_name_prefix}-s7-{stamp}",
        data_source_config=fill(definitions.definition["data_source_config"], definitions, substitutions),
        testing_criteria=fill(definitions.definition["testing_criteria"], definitions, substitutions),
    )
    print(f"eval {evaluation.id}")

    heading("3. Upload the rows and start a run")
    dataset = project.datasets.upload_file(name=f"{config.foundry.dataset_name_prefix}-s7", version=stamp,
                                           file_path=str(args.items))
    substitutions["dataset_id"] = dataset.id
    run = openai.evals.runs.create(
        eval_id=evaluation.id, name=f"s7-{stamp}",
        data_source=fill(definitions.definition["run_data_source"], definitions, substitutions),
    )
    started = time.monotonic()
    while run.status not in TERMINAL and time.monotonic() - started < args.timeout:
        time.sleep(config.foundry.poll_interval_s)
        run = openai.evals.runs.retrieve(run.id, eval_id=evaluation.id)
        print(f"run {run.id}: {run.status}")
    items = list(openai.evals.runs.output_items.list(run.id, eval_id=evaluation.id))
    record.update(eval=evaluation.model_dump(mode="json"), run=run.model_dump(mode="json"),
                  output_items=[item.model_dump(mode="json") for item in items],
                  elapsed_s=round(time.monotonic() - started))
    path = save("s7", "foundry-eval", record)

    heading("4. Results (compare with: uv run evals score evals/evaluators/samples/eval-items.jsonl)")
    counts, report = getattr(run, "result_counts", None), getattr(run, "report_url", None)
    print(f"status {run.status}; counts {counts}; report {report}")
    for item in record["output_items"]:
        row = (item.get("datasource_item") or {}).get("case_id", "?")
        scores = ", ".join(f"{r.get('name')}={r.get('score')}{'' if r.get('passed') else ' (fail)'}"
                           for r in item.get("results", []))
        print(f"- {row}: {scores}")
    print(f"\nFor ADR-008: registration errors, version pinning, errored rows, threshold semantics, cost. Raw: {path}")


if __name__ == "__main__":
    main()
