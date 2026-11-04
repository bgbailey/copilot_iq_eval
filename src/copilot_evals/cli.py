"""The ``evals`` command-line interface (PLAN §8, P2.1).

Commands are added by the backlog tasks that own them. Available today:

* ``evals validate``  Offline checks of the golden set and of the evaluation definitions in
                      ``evals/evaluators/``. No tenant, network or credentials needed.
* ``evals score``     Score evaluation rows that were already collected (``eval_items.jsonl``) on the
                      chosen backend. The local backend needs no Azure resources.
* ``evals deploy``    Set up a demo tenant: ``deploy fabric`` builds and validates the Fabric estate,
                      ``deploy workiq`` uploads the Work IQ documents (docs/deployment.md).

Planned (see docs/backlog/tasks.yaml): ``evals run`` (P2.6), ``evals foundry sync`` (P2.7),
``evals auth login|check`` (P2.3), ``evals publish`` (P8.1) and ``evals fixtures record`` (P3.2).
Every verdict comes from the evaluators in ``evals/evaluators/``, run by Microsoft Foundry Evaluations
or by the local backend (ADR-007, ADR-009); no other code scores an answer.
"""

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from copilot_evals import __version__
from copilot_evals.evaluation.backend import BackendName, EvaluationRun
from copilot_evals.evaluation.dataset import EvalItemsError, read_eval_items, write_evaluation_run
from copilot_evals.evaluation.definitions import (
    DefinitionError,
    EvaluationDefinitions,
    check_definitions,
    load_definitions,
)
from copilot_evals.evaluation.local import LocalBackend
from copilot_evals.evaluation.verdict import attempt_outcome
from copilot_evals.golden import Finding, GoldenSet, GoldenSetError, Severity, check_golden_set, load_golden_set
from copilot_evals.schemas import EvalItem, EvaluatorResult, Outcome
from copilot_evals.setup.commands import deploy_app

DEFAULT_GOLDEN_DIR = Path("evals/golden")
DEFAULT_EVALUATORS_DIR = Path("evals/evaluators")

_OUTCOME_STYLE = {Outcome.PASS: "green", Outcome.FAIL: "red", Outcome.INCONCLUSIVE: "yellow"}

app = typer.Typer(
    name="evals",
    help="Copilot x Fabric IQ evaluation harness. Design: docs/PLAN.md.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(deploy_app, name="deploy")
console = Console()
err_console = Console(stderr=True)


def _show_version(value: bool) -> None:
    """Print the package version and stop (eager ``--version`` option)."""
    if value:
        console.print(f"copilot-fabriciq-evals {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_show_version, is_eager=True, help="Show the version and exit."),
    ] = False,
) -> None:
    """Copilot x Fabric IQ evaluation harness."""


@app.command()
def validate(
    golden_dir: Annotated[
        Path,
        typer.Option("--golden-dir", help="Folder holding cases.yaml, personas.yaml and models.yaml."),
    ] = DEFAULT_GOLDEN_DIR,
    evaluators_dir: Annotated[
        Path,
        typer.Option("--evaluators-dir", help="Folder holding the evaluator catalog, source and eval definition."),
    ] = DEFAULT_EVALUATORS_DIR,
    strict: Annotated[bool, typer.Option("--strict", help="Fail on warnings as well as errors.")] = False,
) -> None:
    """Check the golden set and the evaluation definitions offline."""
    try:
        golden = load_golden_set(golden_dir)
        definitions = load_definitions(evaluators_dir)
    except (GoldenSetError, DefinitionError) as exc:
        err_console.print(f"[bold red]error[/] {escape(str(exc))}", soft_wrap=True)
        raise typer.Exit(code=1) from exc

    _print_golden_summary(golden_dir, golden)
    _print_evaluators_summary(evaluators_dir, definitions)
    findings = check_golden_set(golden) + check_definitions(definitions)
    _print_findings(findings)

    errors = sum(1 for finding in findings if finding.severity == Severity.ERROR)
    warnings = len(findings) - errors
    if errors or (strict and warnings):
        console.print(f"[bold red]FAILED[/] {errors} error(s), {warnings} warning(s)")
        raise typer.Exit(code=1)
    console.print(f"[bold green]OK[/] {errors} error(s), {warnings} warning(s)")


@app.command()
def score(
    items_file: Annotated[
        Path,
        typer.Argument(help="JSONL file with one evaluation row (EvalItem) per line.", exists=True, dir_okay=False),
    ],
    backend: Annotated[
        BackendName,
        typer.Option("--backend", help="Where the evaluators run: local (this process) or foundry."),
    ] = BackendName.LOCAL,
    evaluators_dir: Annotated[
        Path,
        typer.Option("--evaluators-dir", help="Folder holding the evaluator catalog, source and eval definition."),
    ] = DEFAULT_EVALUATORS_DIR,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Folder to write evaluator_results.jsonl and evaluation_run.json to."),
    ] = None,
) -> None:
    """Score evaluation rows that were already collected, and show each attempt's verdict and reasons.

    The local backend runs the evaluators in this process and needs no Azure resources. Without an AI
    judge, the judge's results are INCONCLUSIVE.
    """
    if backend == BackendName.FOUNDRY:
        message = "the Foundry backend client is not built yet (backlog task P2.7); use --backend local"
        err_console.print(f"[bold red]error[/] {message}", soft_wrap=True)
        raise typer.Exit(code=2)
    try:
        definitions = load_definitions(evaluators_dir)
        items = read_eval_items(items_file)
        local = LocalBackend(definitions)
        evaluation = local.evaluate(items)
    except (DefinitionError, EvalItemsError) as exc:
        err_console.print(f"[bold red]error[/] {escape(str(exc))}", soft_wrap=True)
        raise typer.Exit(code=1) from exc

    _print_evaluation(evaluators_dir, items, evaluation, judge=local.has_judge)
    if out is not None:
        write_evaluation_run(out, evaluation)
        console.print(f"Results written to [bold]{escape(str(out))}[/]")


def _print_golden_summary(golden_dir: Path, golden: GoldenSet) -> None:
    """Print a one-screen overview of the golden set."""
    cases = golden.cases
    criticality = Counter(case.criticality.value for case in cases)
    behaviors = Counter(case.expect.behavior.value for case in cases)
    decoys = sorted(key for key, model in golden.models.items() if model.decoy)

    rows = [
        ("cases", f"{len(cases)} ({_counts(criticality)})"),
        ("intents", str(len({case.intent for case in cases}))),
        ("behaviours", _counts(behaviors)),
        ("personas", f"{len(golden.personas)} ({', '.join(golden.personas)})"),
        ("models", f"{len(golden.models)} (decoys: {', '.join(decoys) or 'none'})"),
        ("documents", f"{len(golden.documents)} ({', '.join(golden.documents) or 'none'})"),
    ]
    console.print(f"Golden set [bold]{escape(str(golden_dir))}[/]")
    for name, value in rows:
        console.print(f"  {name:<11} {escape(value)}", soft_wrap=True)


def _print_evaluators_summary(evaluators_dir: Path, definitions: EvaluationDefinitions) -> None:
    """Print the evaluators and testing criteria that either backend runs."""
    kinds = Counter(spec.kind for spec in definitions.evaluators.values())
    criteria = [str(criterion.get("name")) for criterion in definitions.criteria]
    console.print(f"Evaluators [bold]{escape(str(evaluators_dir))}[/]")
    console.print(f"  {'evaluators':<11} {len(definitions.evaluators)} ({escape(_counts(kinds))})", soft_wrap=True)
    console.print(f"  {'criteria':<11} {escape(', '.join(criteria))}", soft_wrap=True)
    console.print(f"  {'row fields':<11} {len(definitions.item_fields)}")
    console.print(f"  {'backends':<11} {', '.join(name.value for name in BackendName)} (one set of evaluators)")


def _print_evaluation(evaluators_dir: Path, items: list[EvalItem], run: EvaluationRun, *, judge: bool) -> None:
    """Print every attempt's verdict with its evaluator results and reasons, then the totals."""
    by_attempt: dict[str, list[EvaluatorResult]] = {}
    for result in run.results:
        by_attempt.setdefault(str(result.attempt_id), []).append(result)

    console.print(f"Scored [bold]{len(items)}[/] evaluation rows on the [bold]{run.backend.value}[/] backend")
    console.print(f"  {'evaluators':<11} {escape(str(evaluators_dir))} ({len(run.evaluator_versions)} criteria)")
    judge_status = "configured" if judge else "not configured, so the AI judge's results are INCONCLUSIVE"
    console.print(f"  {'AI judge':<11} {judge_status}", soft_wrap=True)

    verdicts: Counter[Outcome] = Counter()
    for item in items:
        results = by_attempt.get(str(item.attempt_id), [])
        verdict = attempt_outcome(results)
        verdicts[verdict] += 1
        title = f"{item.case_id} · {item.surface} · {item.persona} · attempt {item.attempt_no}"
        console.print(f"\n[bold]{escape(title)}[/]  {_styled(verdict)}")
        width = max((len(result.evaluator) for result in results), default=0)
        for result in results:
            reason = f"  {escape(result.reason)}" if result.reason else ""
            console.print(f"  {result.evaluator:<{width}}  {_styled(result.outcome)}{reason}", soft_wrap=True)

    totals = ", ".join(f"{verdicts[outcome]} {_styled(outcome)}" for outcome in Outcome)
    console.print(f"\nAttempts: {totals}")


def _styled(outcome: Outcome) -> str:
    """An outcome in its colour: PASS green, FAIL red, INCONCLUSIVE yellow."""
    return f"[{_OUTCOME_STYLE[outcome]}]{outcome.value}[/]"


def _print_findings(findings: list[Finding]) -> None:
    """Print each finding on one line, errors in red and warnings in yellow."""
    for finding in findings:
        style = "red" if finding.severity == Severity.ERROR else "yellow"
        label = finding.severity.value.upper()
        console.print(f"[{style}]{label:<8}[/] {escape(finding.where)}: {escape(finding.message)}", soft_wrap=True)


def _counts(counter: Counter[str]) -> str:
    """Format a counter as ``a 3, b 1`` in descending order of count."""
    return ", ".join(f"{key} {count}" for key, count in counter.most_common())
