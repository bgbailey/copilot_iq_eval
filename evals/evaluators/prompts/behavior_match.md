You are grading how an AI assistant's answer to a business-data question behaved. You are not grading whether its numbers are correct: other checks do that.

Decide which ONE behaviour the answer shows:

- answer: it gives a specific figure or result for the question.
- clarify: it asks the user a question to pin down the metric, period or scope, and gives no figure.
- refuse: it says plainly that no available source holds this data or that the question is out of scope, and gives no figure.
- no_access: it says the user can't access the data or the source that holds the answer, and doesn't answer from another source.

An answer that gives a figure and also asks a follow-up question is "answer".

Expected behaviour: {{expected_behavior}}

Question:
{{query}}

Answer to grade:
{{response}}

Rate from 1 to 5 how clearly the answer shows the expected behaviour:

5 - clearly the expected behaviour
4 - the expected behaviour, with minor hedging or extra content
3 - mixed or unclear
2 - mostly a different behaviour
1 - clearly a different behaviour

Output Format (JSON):
{
  "result": <integer from 1 to 5>,
  "reason": "Observed: <answer|clarify|refuse|no_access>. <one sentence explaining the score>"
}
