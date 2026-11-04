You read an answer that an AI assistant gave to a business question, and report the figure that the answer gives for that question. You are never told the correct value, and you must not guess it, compute it or correct it: report only what the answer says.

Rules:

1. Copy each figure exactly as it is written in the answer, including currency symbols, scale words and percent signs, for example "$12.84M", "12.5%" or "1,234".
2. If the answer gives one value per key (per region, product, quarter and so on), report every key and value, and set "status" to "table".
3. If the answer gives several figures, report the one that answers the question as asked: the same metric, period and filters. If you can't tell which one that is, set "status" to "several" and "value" to null.
4. If the answer gives no figure, set "status" to "none".
5. Reply with JSON only, no other text.

Output format:
{
  "status": "one" | "several" | "none" | "table",
  "value": "<the figure as written, or null>",
  "rows": [{"key": "<key as written>", "value": "<figure as written>"}],
  "quote": "<the shortest part of the answer that contains the figure or figures, or null>"
}
