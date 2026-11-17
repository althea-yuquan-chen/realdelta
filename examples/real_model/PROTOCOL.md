# Haiku demo protocol (pre-registered)

This file, the task generator, the runner and their tests are committed before any paid call.
Commit order is the pre-registration record. Everything that decides the reported result is fixed
below; nothing is chosen after seeing model output.

## Model and request

- Model `claude-haiku-5-5` (Claude Haiku 5.5). One Messages API request per trial: a system prompt,
  one user message, `max_tokens=2048`, `output_config={"effort": "low"}`. No `temperature`, `top_p`
  or `top_k` (non-default values are rejected on this model), no caching, no batches, no tools.
  Thinking is left at the model default (adaptive); thinking content is never stored.
- The client is created with `max_retries=0` and `timeout=120` seconds, so every retry is made and
  logged by the runner.
- The API key is read by the SDK from the environment. It is never passed on a command line, written
  to a file or logged; no response headers, exception reprs or environment variables are stored.

## Task set (`tasks.jsonl`, written by `make_tasks.py`, seed 20261120)

40 cases, 10 per family, determined only by the seed and the rules below. No case is added, removed
or changed after any model call, whatever the results (including all arms passing every case).

1. Arithmetic: "A shop has {a} boxes with {b} items in each box. It sells {c} items and then receives
   {d} more boxes of {b} items. How many items does it have now?" a in 3..19, b in 4..29,
   c in 1..a*b-1, d in 2..9. Answer a*b - c + d*b. Form: an integer with no units or separators.
2. Letter count: a made-up word of 9-14 letters drawn from 6 letters, and a letter that occurs 2-5
   times in it. "How many times does the letter '{x}' appear in the word '{w}'?" Form: an integer.
3. Weekday: a date from 2026-01-01 to 2030-12-31 and n in 20..400. "What day of the week is {n} days
   after {date}?" Form: the full English weekday name, e.g. Monday.
4. Sort: a sentence containing 5-7 distinct integers from 1..999. "List the numbers in this sentence
   in ascending order: {sentence}" Form: the numbers separated by commas, no spaces.

User message = the question + a blank line + "Give the answer in this form: {form}". The exact text
of every case is in `tasks.jsonl`.

## Arms

- System prompt S0 (baseline): "You are solving a short puzzle. Work it out, then give the final
  answer on the last line in the form ANSWER: <value>."
- System prompt S1 (candidate): S0 + " Answer immediately; do not show your working."
- Arm A1 = S0, arm A2 = S0 (an independent re-run), arm B = S1. 5 trials per case per arm,
  600 calls in total. Because thinking stays on, S1 changes the visible output; the model can still
  reason internally. B is described as "a prompt edit asking for no visible working".

## Call order (A3)

All 600 (case, arm, trial) calls are issued sequentially in one random permutation, seed 20261121,
so that drift or an outage window affects the arms alike.

## Grading

Take the final text block of the response (empty if none). Take its last non-empty line, delete
every `*` and backtick character in it (no expected answer contains them), and strip surrounding
whitespace. The whole line must match `ANSWER:\s*(.+)`, anchored at the start (case-sensitive
"ANSWER:"; "The answer is ANSWER: 42" does not match). The captured value, with surrounding whitespace
and one trailing period removed, must equal the expected answer: exactly for families 1, 2 and 4
(family 4 after removing all spaces), case-insensitively for family 3.

Each trial gets exactly one category, the first that applies in this order: `timeout`, `refusal`
(stop reason refusal), `max_tokens` (stop reason max_tokens, even if an answer line is present),
`empty`, `no_answer_line`, `wrong_value`, `pass`. Categories are reported per arm (descriptive, not
a second result). Every category except `pass` is a fail.

## Errors and retries (A4)

- Rate-limit (429), server errors (5xx, including 529) and connection errors happen before the model
  produces an answer: the runner re-issues the same request after a backoff (2, 4, 8, 16, 32 s; at
  most 5 times per call), and logs every re-issue.
- A client timeout (120 s) depends on output length, so it is not re-issued: the trial is a fail
  (`timeout`). This includes timeouts while connecting, a small conservative bias that affects all
  arms alike.
- Any other 4xx means the request is wrong: the run aborts.
- Every case gets exactly 5 trials per arm.

## Limits

The run stops when any limit would be crossed: 60 re-issues in total; 1,400,000 output tokens in
total; $1.00 estimated from `usage` at $0.10 / $0.50 per million input / output tokens (the
constants are printed by `--dry-run` for checking against the official price page; the bill in the
Console is authoritative). Expected cost about $0.17, worst case (every call at 2,048 output tokens)
about $0.63.

## Preflight

Before the run, 2 calls (one per system prompt) on a question outside the task set ("What is 17 + 25?
Give the answer in this form: an integer.") check that the request shape is accepted. They are
logged in the run directory and their answers are not used. If the request is rejected, the request
code is fixed and the change is recorded as an amendment below before the run. The grader is not
changed after the preflight except by an amendment.

## Abort and re-run

The runner appends each record to disk as soon as the call returns, so an aborted run keeps
everything done so far. An aborted run is committed as it is (in its own directory) and disclosed in
the README; it is not reported as a result.

- Re-run allowed (same task set, same order seed, new directory), because the cause does not depend
  on model output: a call that exhausts its 5 re-issues, the 60 re-issue limit, an outage, or an
  account error (401, 403, insufficient balance).
- Re-run allowed after a fix: a crash of the runner itself (unexpected response shape, a file error).
  The fix is recorded as an amendment below before the re-run.
- No re-run: a stop at the cost or output-token limit caused by normal responses, or a 4xx caused by
  the request itself after the preflight passed (that is a protocol failure; the owner decides).
- An operator interrupt (Ctrl-C) is recorded as an abort; whether to re-run is the owner's call and is
  disclosed in the README.
- Abort records give the error class, HTTP status and the API's error type (a fixed enum), never the
  message, so the cause can be classified without storing request or account details.
- At most one re-run in total. If it also aborts, stop; the owner decides.

## Analysis (exact commands, run in the run directory)

```
python -m realdelta interval a1.jsonl --json
python -m realdelta interval a2.jsonl --json
python -m realdelta interval b.jsonl --json
python -m realdelta interval a1.jsonl --scope population --json
python -m realdelta compare a1.jsonl a2.jsonl --seed 0 --n-perm 10000 --conf 0.95 --json
python -m realdelta compare a1.jsonl b.jsonl --seed 0 --n-perm 10000 --conf 0.95 --json
```

Result files carry `case_id`, `passed` and `trial`. "Flagged" and "detected" mean the `compare`
interval excludes 0 (`detected` in its output); the p-value is recorded but does not decide anything.
The population-scope interval is reported for A1 because the cases are random draws from the
generator: the population is an equal mix of the four puzzle generators, and treating the stratified
sample (10 per family) as independent draws is usually conservative. It describes puzzles from this
generator, not any other task set.

## How the README will state each outcome

- A1 vs A2 not flagged: "The A/A pair was not flagged. It is one realisation: in the synthetic demo,
  4.6% of unchanged pairs were flagged."
- A1 vs A2 flagged: "The A/A pair was flagged, a false alarm by construction. Such alarms happen:
  4.6% of unchanged pairs in the synthetic demo, and the calibration tests allow up to 7%." The run is
  still reported in full.
- A1 vs B detected: "Asking for no visible working changed the pass rate by {estimate}, 95% interval
  [{low}, {high}]", plus the per-arm failure categories, so a reader can see whether formatting or
  accuracy moved.
- A1 vs B not detected: "No change detected at this scale (40 cases, 5 trials); the interval
  [{low}, {high}] bounds the change." Never "no effect".
- Always: A1 appears in both comparisons, so they are not independent; each of the two comparisons
  can raise a false alarm (4.6% of unchanged pairs in the synthetic demo; the calibration tests allow
  up to 7%); the task set is synthetic and says nothing about other tasks.

Power for this task set is unknown before the run; as a rough scale only, `plan_scale.txt` (committed
with this protocol) holds `realdelta plan` outputs for 40 cases and 5 trials under two synthetic
settings.

## Amendments

### Amendment 1 (2026-11-16): GPT-5.6 Luna instead of Claude Haiku 5.5

Made before any paid call: the owner has no Claude API access. No model output of any kind had been
seen. Task set, seeds, arms, prompts, trial counts, call order, grading rule, retry and abort rules,
analysis commands and README wording stay as above, except where this amendment says otherwise.
The directory moved from `examples/haiku/` to `examples/real_model/`.

- Model GPT-5.6 Luna (OpenAI's nano tier), served through Azure OpenAI on the owner's personal
  subscription: a Global Standard deployment named `gpt-5.6-luna` (Microsoft lists `gpt-5.6-luna`
  version 2026-07-09 for the Responses API). Chosen by the owner as the cheapest and lowest tier, where
  some errors on these puzzles are more likely; that expectation is not tested before the run.
- Endpoint and key: Microsoft's documented v1 pattern, the standard `openai.OpenAI` client with
  `base_url` = `https://<resource>.openai.azure.com/openai/v1/` and the key, read from the environment
  variables `AZURE_OPENAI_BASE_URL` and `AZURE_OPENAI_API_KEY`, which the owner sets outside the
  program. Their values are never printed, logged or written; provenance records the deployment name
  and the model id returned, not the endpoint. If either variable is missing the run does not start.
- Request: Responses API, one request per trial: `model` = the deployment name, `instructions` = the
  system prompt (S0 or S1),
  `input` = the user message, `max_output_tokens=2048` (reasoning and visible output together),
  `reasoning={"effort": "low"}`. No `temperature` or `top_p`, no tools, no previous-response chaining.
  Reasoning items are never stored; only the message text is kept.
- Client: `openai.OpenAI(api_key=..., base_url=..., max_retries=0, timeout=120)`.
- Error classes: `openai.APITimeoutError` is a timeout (checked first; in the installed SDK it
  subclasses `APIConnectionError`); `openai.APIConnectionError` is re-issued; `openai.APIStatusError`
  with status 429 or >= 500 is re-issued; a 400 with code `content_filter` (Azure's input guardrail,
  documented by Microsoft) is the `refusal` category for that trial, not an abort and not re-issued;
  any other error aborts.
- Text and stop reason: the text is built from the `output_text` parts of the response's `message`
  items (see "Text" below). A `refusal` content part, `status="incomplete"` with
  `incomplete_details.reason="content_filter"`, or an Azure `content_filters` entry with
  `blocked=true` and `source_type="completion"` is the `refusal` category.
  `status="incomplete"` with reason `max_output_tokens` is the `max_tokens` category. Any other
  incomplete reason is a new category `incomplete_other` (a fail), placed after `max_tokens` in the
  precedence order: `timeout`, `refusal`, `max_tokens`, `incomplete_other`, `empty`,
  `no_answer_line`, `wrong_value`, `pass`.
- A response whose `status` is not `completed` or `incomplete` (failed, cancelled, queued,
  in_progress), or that has no usage, is not an answer attempt: it is treated like a server error,
  re-issued under the same backoff and counted toward the re-issue limits; only its status and
  `error.code` are recorded. It is never graded.
- A 429 with code or type `insufficient_quota` (no credit) aborts at once instead of being re-issued;
  it is an account cause, so a re-run is allowed.
- Text: the `output_text` parts of all `message` items, joined with a newline (so an answer line in a
  separate part stays on its own line); the grading rule then takes the last non-empty line as above.
- `store=False` is sent, so responses are not kept on the provider's side. Automatic prompt caching
  does not apply to prompts this short (each request is about 100 tokens); no caching is requested.
- Usage: `usage.input_tokens` and `usage.output_tokens` (the latter includes reasoning tokens).
- Price on Azure is uncertain: Microsoft's Foundry blog lists Luna Global Standard at $0.20 / $1.20
  per million input / output tokens from 2026-08-01, users in Microsoft Q&A report being billed at
  the older $1 / $6, and the public pricing page shows placeholders. The cost limit therefore uses
  $1 / $6. Expected cost about $2.35 (300 input and 600 output tokens per call, an assumption);
  worst case, every call at 2,048 output tokens, about $7.58. The Azure bill is authoritative.
- Limits: 60 re-issues; 1,400,000 output tokens; $8.00 estimated at $1 / $6 per million (at this
  price the cost limit binds before the token limit). The owner chose the $8.00 cap.
- Sequential calls stay far below the documented Global Standard quota for Luna (250 requests and
  250,000 tokens per minute at tier 1), so throttling is not expected; if it happens, the re-issue
  rules above apply.
- Preflight: if either preflight call is a refusal (including Azure's 400 `content_filter`), the run
  aborts before any task call. The preflight question is outside the task set, so this is a
  configuration cause: a re-run is allowed after the fix. Each record notes whether the response
  carried Azure's `content_filters` field, so a missing filter signal is visible.
- `summary.txt` gives the cost as an upper estimate at $1 / $6; the README quotes token counts, and
  any dollar amount it quotes comes from the Azure bill.
- README wording above that names the model refers to GPT-5.6 Luna served through Azure OpenAI; Azure's
  content filtering is part of the system measured and feeds the `refusal` category.
