"""Allow ``python -m copilot_evals`` as an alias for the ``evals`` command."""

from copilot_evals.cli import app

if __name__ == "__main__":
    app(prog_name="evals")
