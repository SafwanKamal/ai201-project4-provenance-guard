# Provenance Guard Planning

## Architecture

```text
Submission flow
Client
  | POST /submit {text, creator_id}
  v
Flask API validation
  | raw text
  v
Signal 1: LLM-style classifier
  | ai_likelihood score, rationale
  v
Signal 2: stylometric heuristics
  | ai_likelihood score, metrics
  v
Confidence scoring
  | combined score + attribution bucket
  v
Transparency label generator
  | exact reader-facing label
  v
Audit log
  | structured classification event
  v
JSON response {content_id, attribution, confidence, label, signals}

Appeal flow
Client
  | POST /appeal {content_id, creator_reasoning}
  v
Flask API validation
  | appeal text + original decision
  v
Content status update
  | status = under_review
  v
Audit log
  | structured appeal event
  v
JSON response {content_id, status, message}
```

The submission endpoint validates the request, runs two independent detection signals, combines their scores into a calibrated AI-likelihood confidence, generates a plain-language transparency label, writes a structured audit entry, and returns the decision. The appeal endpoint uses the returned `content_id`, records the creator's reasoning, changes the status to `under_review`, and appends an appeal event to the audit log.

## Detection Signals

Signal 1 is an LLM-style classifier. With `GROQ_API_KEY` set, the app asks `llama-3.3-70b-versatile` to return JSON containing a score from `0` to `1`, where `1` means very likely AI-generated and `0` means very likely human-written. It captures holistic semantic and stylistic coherence, but it can be overconfident on polished human writing and cannot prove authorship.

When no API key is available, the project uses a deterministic local fallback that imitates the same output contract. The fallback looks for formal AI-associated phrasing, average sentence length, conversational markers, contractions, and emphatic casing. This keeps the demo testable without pretending the fallback is as strong as a real model.

Signal 2 is stylometric heuristics. It measures sentence length uniformity, type-token ratio, average sentence length, and punctuation density. It outputs a score from `0` to `1`, where highly uniform, polished, lower-diversity text is more AI-like. It is independent from the LLM-style signal because it measures structure rather than meaning, but it may misread formal academic writing, short poems, or deliberately minimal prose.

The combined confidence score uses `70%` LLM-style score and `30%` stylometric score. The holistic signal receives more weight because false positives are harmful and a purely structural metric can over-penalize unusual human writing. If the two signals disagree by more than `0.30`, the result is pulled slightly toward `0.50` to represent uncertainty.

## Uncertainty Representation

A score of `0.50` means the system has no reliable basis to call the text AI-generated or human-written. Scores near the middle should produce an uncertainty label, not a forced binary verdict.

Thresholds:

| Combined score | Attribution | Meaning |
| --- | --- | --- |
| `0.70` to `1.00` | `likely_ai` | Strong AI-like signals |
| `0.31` to `0.69` | `uncertain` | Mixed or weak evidence |
| `0.00` to `0.30` | `likely_human` | Strong human-like signals |

These thresholds intentionally make false positives harder: the system needs stronger evidence to label a creator's work as AI-generated.

## Transparency Label Design

| Variant | Exact label text |
| --- | --- |
| High-confidence AI | "Likely AI-generated: Our system found strong signals that this text may have been generated or heavily assisted by AI. This is not a final judgment; the creator can appeal if the label is wrong." |
| High-confidence human | "Likely human-written: Our system found strong signals that this text appears to be original human writing. Detection is not perfect, so this label should be read as helpful context rather than proof." |
| Uncertain | "Attribution uncertain: Our system does not have enough confidence to label this text as AI-generated or human-written. Readers should avoid making assumptions, and the creator may provide more context." |

## Appeals Workflow

Any creator with the `content_id` returned by `/submit` can appeal by sending `content_id` and `creator_reasoning` to `POST /appeal`. The system stores the reasoning, updates the content status to `under_review`, and writes a structured audit entry that includes the original attribution, confidence, both signal scores, and appeal reasoning.

A human reviewer would see the content ID, creator ID, original label, confidence, individual signal scores, stylometric metrics, and the creator's explanation. The system does not automatically reclassify appeals because the project goal is to provide a fair review path, not to pretend automated detection is final.

## API Surface

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | GET | Confirm the service is running |
| `/submit` | POST | Analyze text and return attribution, confidence, label, and signals |
| `/appeal` | POST | Contest a decision and move status to `under_review` |
| `/log` | GET | Return recent structured audit log entries for grading/demo evidence |

## Anticipated Edge Cases

Short poems may be misclassified because repetition, sparse punctuation, and low vocabulary diversity can look AI-like to the stylometric signal even when the poem is human-written.

Formal human essays may receive elevated AI-likelihood scores because polished transitions, even sentence lengths, and academic vocabulary overlap with common AI output patterns.

Heavily edited AI output with personal anecdotes may land in the uncertain range because human markers can lower the LLM-style fallback score while stylometry still sees uniform structure.

Very short submissions are inherently hard to score because both signals have too little evidence. The fallback pulls short-text scores toward uncertainty.

## AI Tool Plan

M3 submission endpoint and first signal: provide the detection signal section and architecture diagram. Ask for a Flask skeleton, a `/submit` route, and an LLM-style signal function returning `{score, rationale, source}`. Verify by calling the signal directly and then posting a sample request to `/submit`.

M4 second signal and confidence scoring: provide the detection signals, uncertainty thresholds, and architecture diagram. Ask for the stylometric signal and scoring combiner. Verify with four inputs: clearly AI-like, clearly human-like, formal borderline, and lightly edited AI-like text.

M5 production layer: provide the label variants, appeals workflow, rate-limit requirement, and architecture diagram. Ask for label mapping, `/appeal`, `/log`, structured audit entries, and Flask-Limiter configuration. Verify that all three labels are reachable, appeal changes status to `under_review`, and rapid submit requests produce `429` after the configured limit.

## Stretch Feature: Analytics Dashboard

Before adding stretch work, I updated the plan to include an analytics dashboard. The dashboard should show detection patterns, appeal rates, and average confidence using data from the structured audit log.

Implementation plan:

| Item | Decision |
| --- | --- |
| Data source | Reuse `audit_log.jsonl` so analytics reflect the same canonical evidence as `/log` |
| Endpoint | Add `GET /analytics` returning total decisions, attribution counts, appeal count, appeal rate, and average confidence |
| View | Add `GET /` as a lightweight dashboard with a submission tester, appeal action, recent audit log, and analytics summary |
| Verification | Submit at least three samples, file one appeal, confirm dashboard and `/analytics` update |
