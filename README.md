# Provenance Guard

Provenance Guard is a Flask backend that classifies text submissions as likely AI-generated, likely human-written, or uncertain. It returns a confidence score, a reader-facing transparency label, structured signal details, rate limits submission traffic, and supports creator appeals.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run
```

Optional Groq support:

```bash
cp .env.example .env
# add GROQ_API_KEY=your_key_here
```

Without a Groq key, the app uses a deterministic local fallback for the LLM-style signal so the project remains runnable for review.

## API

Submit content:

```bash
curl -s -X POST http://localhost:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text":"Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment.","creator_id":"test-user-1"}' | python3 -m json.tool
```

Appeal a decision:

```bash
curl -s -X POST http://localhost:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id":"PASTE-CONTENT-ID-HERE","creator_reasoning":"I wrote this myself from personal experience. My writing style may appear formal because English is not my first language."}' | python3 -m json.tool
```

View audit log:

```bash
curl -s http://localhost:5000/log | python3 -m json.tool
```

View analytics:

```bash
curl -s http://localhost:5000/analytics | python3 -m json.tool
```

## Architecture Overview

A submission enters `POST /submit` with `text` and `creator_id`. The API validates it, sends the text through an LLM-style classifier and a stylometric heuristic classifier, combines the two scores into one confidence score, maps that score to an attribution bucket, generates the transparency label, writes a structured audit event, and returns the result with a unique `content_id`.

Appeals enter `POST /appeal` with `content_id` and `creator_reasoning`. The app updates that content's status to `under_review` and writes an appeal event alongside the original classification evidence.

The full architecture diagram and spec are in `planning.md`.

## Detection Signals

Signal 1 is an LLM-style classifier. If `GROQ_API_KEY` is configured, it calls Groq's `llama-3.3-70b-versatile` and asks for a JSON score between `0` and `1`, where `1` means very likely AI-generated. This signal captures holistic writing quality, coherence, and semantic style. It can miss cases where a human writes in a polished, generic style, and it cannot prove authorship.

Signal 2 is stylometric heuristics. It computes sentence length variance, type-token ratio, punctuation density, and average sentence length. This catches structural patterns such as unusually even sentence pacing or low vocabulary diversity. It misses context and can struggle with short poems, formal essays, or intentionally simple prose.

## Confidence Scoring

The combined confidence score is an AI-likelihood score:

```text
combined = 0.70 * llm_score + 0.30 * stylometric_score
```

If the signals disagree by more than `0.30`, the result is pulled toward `0.50` to reflect uncertainty. Scores `>= 0.70` become `likely_ai`, scores `<= 0.30` become `likely_human`, and everything between becomes `uncertain`. This middle band is intentionally wide because false positives against human creators are more harmful than uncertain labels.

Example outputs from local verification:

| Input type | Attribution | Confidence |
| --- | --- | --- |
| Formal AI-like paragraph about AI ethics | `likely_ai` | `0.712` |
| Casual ramen review with uneven style | `likely_human` | `0.132` |
| Formal monetary policy paragraph | `uncertain` | `0.566` |
| Lightly edited remote-work paragraph | `uncertain` | `0.404` |

## Transparency Labels

| Variant | Exact displayed text |
| --- | --- |
| High-confidence AI | "Likely AI-generated: Our system found strong signals that this text may have been generated or heavily assisted by AI. This is not a final judgment; the creator can appeal if the label is wrong." |
| High-confidence human | "Likely human-written: Our system found strong signals that this text appears to be original human writing. Detection is not perfect, so this label should be read as helpful context rather than proof." |
| Uncertain | "Attribution uncertain: Our system does not have enough confidence to label this text as AI-generated or human-written. Readers should avoid making assumptions, and the creator may provide more context." |

## Appeals Workflow

Creators can contest a decision through `POST /appeal`. They provide the original `content_id` and their reasoning. The app stores the appeal in memory for the current run, changes the status to `under_review`, and appends an appeal event to `audit_log.jsonl` with the original confidence and signal scores.

For a real platform, the reviewer queue would require authentication and durable database storage. For this project, the structured log and status update demonstrate the workflow end to end.

## Rate Limiting

`POST /submit` is limited to `10 per minute` and `100 per day` per remote address. The minute limit allows a real creator to test several drafts without friction while stopping simple flooding scripts. The daily limit is high enough for normal writing-platform use but low enough to discourage bulk scraping or adversarial probing from one client.

Rate-limit test command:

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:5000/submit \
    -H "Content-Type: application/json" \
    -d '{"text":"This is a test submission for rate limit testing purposes only.","creator_id":"ratelimit-test"}'
done
```

Expected evidence:

```text
200
200
200
200
200
200
200
200
200
200
429
429
```

## Audit Log

Audit events are stored as JSON Lines in `audit_log.jsonl` and returned through `GET /log`. Each classification records timestamp, content ID, creator ID, attribution, confidence, both signal scores, stylometric metrics, status, and whether an appeal was filed. Appeal events include the creator's reasoning and `status: under_review`.

Sample entries:

```json
[
  {
    "event": "classification",
    "attribution": "likely_ai",
    "confidence": 0.712,
    "llm_score": 0.893,
    "stylometric_score": 0.37,
    "status": "classified"
  },
  {
    "event": "classification",
    "attribution": "likely_human",
    "confidence": 0.132,
    "llm_score": 0.0,
    "stylometric_score": 0.305,
    "status": "classified"
  },
  {
    "event": "appeal",
    "attribution": "likely_ai",
    "confidence": 0.712,
    "status": "under_review",
    "appeal_filed": true
  }
]
```

## Stretch Feature: Analytics Dashboard

The project includes a simple analytics dashboard at `GET /`. It lets a reviewer submit text, inspect the returned transparency label, file an appeal for the latest submission, and see recent audit-log entries without leaving the browser.

The dashboard is backed by `GET /analytics`, which summarizes detection patterns, appeal rates, and average confidence:

```json
{
  "total_decisions": 3,
  "appeal_count": 1,
  "appeal_rate": 0.333,
  "average_confidence": 0.47,
  "attribution_counts": {
    "likely_ai": 1,
    "likely_human": 1,
    "uncertain": 1
  }
}
```

## Known Limitations

Short poems with repeated words and simple punctuation may look AI-like to the stylometric signal because the metrics interpret repetition and low vocabulary diversity as uniformity. Formal human essays can also be pushed upward because polished transitions and even sentence lengths overlap with common AI-generated prose.

The in-memory content store means appeals only work for content submitted during the current server process. The audit log persists, but a production version should use SQLite or Postgres for durable content and appeal records.

## Spec Reflection

Writing the spec first made the confidence thresholds and label text concrete before implementation, which prevented the API from collapsing into a binary AI/not-AI response. The main implementation divergence is the local fallback for the Groq signal. The spec assumes Groq as the first signal, but the fallback makes the project reviewable without exposing an API key or requiring live network access.

## AI Usage

I directed AI assistance to turn the project brief into an implementation-ready architecture with two flows: submission and appeal. I revised that plan by widening the uncertain threshold band to reduce the risk of false positives.

I also directed AI assistance to scaffold the Flask app, detection functions, and documentation evidence. I revised the generated approach by adding a Groq-free fallback, adding signal-disagreement calibration, and ensuring the exact three label variants appear in both code and README.
