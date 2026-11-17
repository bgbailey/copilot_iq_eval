# Responsible AI Transparency FAQ

## What is this accelerator?

A small, readable evaluation that asks Microsoft 365 Copilot a set of golden business questions and checks each answer three ways: whether the number matches reference DAX run against the certified semantic model, whether Copilot cited the expected report, and whether the DAX ran on the expected semantic model according to Fabric workspace monitoring. Results are stored in an Eventhouse and shown in a Fabric app built with Rayfin.

## What can it do?

- Show, question by question, whether Copilot's numbers are right and where they came from.
- Catch decoys: sandbox or draft models whose names and numbers look right but aren't.
- Measure whether answers stay right across repeated runs.
- Compare runs before and after you improve a semantic model.

## What is it intended for?

Teaching and demonstrating an evaluation method in a demo tenant, and giving data teams a starting point for checking Copilot over their own semantic models before people rely on it.

## What doesn't it measure?

- Prose quality, tone, helpfulness or safety of Copilot's answers. Use Microsoft Foundry evaluations or the Microsoft 365 Copilot Evaluations CLI for those.
- Every user's experience. Row-level security applies as the one test user; run with other test users to cover other roles.
- Production traffic. It runs a fixed set of questions on demand; it doesn't monitor what real users ask.

## How was it evaluated?

The scoring rules in `eval/scoring.py` were run against the two sets of saved answers in `sample/`, which cover passes, wrong numbers, decoys, missing query logs and a question that should be declined. The live path was designed against the public documentation of the Copilot Chat API, Fabric workspace monitoring and Power BI `executeQueries`; confirm it in your own tenant before relying on the results.

## What are the limitations?

- The Copilot Chat API is a preview (beta) API that accepts delegated sign-in only and needs broad read permissions.
- Query logs are matched to questions by user and time window. That's evidence, not proof: other activity by the test user in the same window adds noise.
- Query logs can arrive late. A late log makes the model check INCONCLUSIVE, never a pass.
- Matching numbers is deliberately simple: the number in the answer closest to the expected value is checked against a tolerance. An answer that lists many numbers can pass by containing the right one.
- The sample data is synthetic and says nothing about your tenant.

## How should it be used responsibly?

- Run it only as a dedicated test user in a demo or test tenant.
- Keep `.env`, the sign-in cache and the `results/` folder on your machine.
- Treat the Eventhouse and the scorecard app as containing Copilot's answers and the DAX it ran, and share them deliberately.
- Use the results to improve semantic models and to decide where people need to double-check Copilot, not as a guarantee that every answer will be right.
