import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from flask import Flask, jsonify, render_template_string, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from detection import analyze_text

app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "audit_log.jsonl")
CONTENT_STORE = {}

DASHBOARD_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Provenance Guard</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17202a;
      --muted: #65717f;
      --line: #d8dee6;
      --panel: #ffffff;
      --page: #f6f8fb;
      --accent: #1f7a8c;
      --warn: #9a5b00;
      --danger: #a63a3a;
      --human: #28724f;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--page);
      color: var(--ink);
      font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 22px clamp(18px, 4vw, 44px);
    }
    h1 { margin: 0; font-size: 28px; letter-spacing: 0; }
    header p { margin: 4px 0 0; color: var(--muted); max-width: 760px; }
    main {
      display: grid;
      grid-template-columns: minmax(320px, 1fr) minmax(320px, 0.9fr);
      gap: 18px;
      padding: 22px clamp(18px, 4vw, 44px);
    }
    section, aside {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    h2 { margin: 0 0 12px; font-size: 18px; }
    label { display: block; margin: 12px 0 6px; font-weight: 650; }
    textarea, input {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 12px;
      font: inherit;
      background: #fff;
    }
    textarea { min-height: 170px; resize: vertical; }
    button {
      margin-top: 12px;
      border: 0;
      border-radius: 6px;
      padding: 10px 14px;
      color: #fff;
      background: var(--accent);
      font-weight: 700;
      cursor: pointer;
    }
    button.secondary { background: #4f5d6b; }
    .stats {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-height: 82px;
    }
    .stat strong { display: block; font-size: 24px; }
    .stat span { color: var(--muted); font-size: 13px; }
    .result {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 180px;
      background: #fbfcfe;
      overflow-wrap: anywhere;
    }
    .badge {
      display: inline-block;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      font-weight: 800;
      color: #fff;
      background: var(--warn);
    }
    .badge.likely_ai { background: var(--danger); }
    .badge.likely_human { background: var(--human); }
    .badge.uncertain { background: var(--warn); }
    pre {
      white-space: pre-wrap;
      background: #111827;
      color: #e5e7eb;
      border-radius: 8px;
      padding: 12px;
      max-height: 320px;
      overflow: auto;
      font-size: 12px;
    }
    .appeal-row {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      margin-top: 12px;
    }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; }
      .stats { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Provenance Guard</h1>
    <p>Submit text for attribution analysis, inspect the confidence score, and file an appeal when a creator contests the result.</p>
  </header>
  <main>
    <section>
      <h2>Submission Tester</h2>
      <label for="creator">Creator ID</label>
      <input id="creator" value="demo-creator">
      <label for="text">Text</label>
      <textarea id="text">Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment.</textarea>
      <button id="submit">Analyze Text</button>
      <button id="sampleHuman" class="secondary">Use Human-Like Sample</button>
      <div class="appeal-row">
        <label for="appealReason">Appeal Reasoning</label>
        <textarea id="appealReason">I wrote this myself and can provide drafts showing my process.</textarea>
        <button id="appeal" class="secondary">Appeal Latest Decision</button>
      </div>
    </section>
    <aside>
      <h2>Analytics</h2>
      <div class="stats">
        <div class="stat"><strong id="total">0</strong><span>decisions</span></div>
        <div class="stat"><strong id="appeals">0</strong><span>appeals</span></div>
        <div class="stat"><strong id="avg">0.000</strong><span>avg confidence</span></div>
      </div>
      <div id="result" class="result">No submission yet.</div>
      <h2 style="margin-top:16px;">Recent Audit Log</h2>
      <pre id="log">[]</pre>
    </aside>
  </main>
  <script>
    let latestContentId = null;

    const humanSample = "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won't go back unless someone drags me there";

    function renderResult(data) {
      latestContentId = data.content_id || latestContentId;
      document.querySelector("#result").innerHTML = `
        <p><span class="badge ${data.attribution}">${data.attribution}</span></p>
        <p><strong>Confidence:</strong> ${data.confidence}</p>
        <p>${data.label}</p>
        <p><strong>Content ID:</strong> ${data.content_id}</p>
      `;
    }

    async function refreshDashboard() {
      const [analyticsResponse, logResponse] = await Promise.all([
        fetch("/analytics"),
        fetch("/log?limit=8")
      ]);
      const analytics = await analyticsResponse.json();
      const log = await logResponse.json();
      document.querySelector("#total").textContent = analytics.total_decisions;
      document.querySelector("#appeals").textContent = analytics.appeal_count;
      document.querySelector("#avg").textContent = analytics.average_confidence.toFixed(3);
      document.querySelector("#log").textContent = JSON.stringify(log.entries, null, 2);
    }

    document.querySelector("#sampleHuman").addEventListener("click", () => {
      document.querySelector("#text").value = humanSample;
    });

    document.querySelector("#submit").addEventListener("click", async () => {
      const response = await fetch("/submit", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          creator_id: document.querySelector("#creator").value,
          text: document.querySelector("#text").value
        })
      });
      const data = await response.json();
      if (!response.ok) {
        document.querySelector("#result").textContent = JSON.stringify(data, null, 2);
        return;
      }
      renderResult(data);
      await refreshDashboard();
    });

    document.querySelector("#appeal").addEventListener("click", async () => {
      if (!latestContentId) {
        document.querySelector("#result").textContent = "Submit content before filing an appeal.";
        return;
      }
      const response = await fetch("/appeal", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          content_id: latestContentId,
          creator_reasoning: document.querySelector("#appealReason").value
        })
      });
      const data = await response.json();
      document.querySelector("#result").textContent = JSON.stringify(data, null, 2);
      await refreshDashboard();
    });

    refreshDashboard();
  </script>
</body>
</html>
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_audit_entry(entry):
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry, sort_keys=True) + "\n")


def read_audit_entries(limit=25):
    if not os.path.exists(AUDIT_LOG_PATH):
        return []
    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as log_file:
        rows = [json.loads(line) for line in log_file if line.strip()]
    return rows[-limit:]


def build_analytics():
    entries = read_audit_entries(100)
    decisions = [entry for entry in entries if entry.get("event") == "classification"]
    appeals = [entry for entry in entries if entry.get("event") == "appeal"]
    attribution_counts = {
        "likely_ai": 0,
        "likely_human": 0,
        "uncertain": 0,
    }

    for decision in decisions:
        attribution = decision.get("attribution")
        if attribution in attribution_counts:
            attribution_counts[attribution] += 1

    average_confidence = 0
    if decisions:
        average_confidence = sum(entry.get("confidence", 0) for entry in decisions) / len(decisions)

    return {
        "total_decisions": len(decisions),
        "appeal_count": len(appeals),
        "appeal_rate": round(len(appeals) / len(decisions), 3) if decisions else 0,
        "average_confidence": round(average_confidence, 3),
        "attribution_counts": attribution_counts,
    }


@app.get("/")
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/submit")
@limiter.limit("10 per minute;100 per day")
def submit():
    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text", "")).strip()
    creator_id = str(payload.get("creator_id", "")).strip()

    if not text:
        return jsonify({"error": "text is required"}), 400
    if not creator_id:
        return jsonify({"error": "creator_id is required"}), 400

    content_id = str(uuid4())
    analysis = analyze_text(text)
    status = "classified"

    CONTENT_STORE[content_id] = {
        "content_id": content_id,
        "creator_id": creator_id,
        "text": text,
        "status": status,
        "analysis": analysis,
        "appeals": [],
    }

    audit_entry = {
        "event": "classification",
        "timestamp": utc_now(),
        "content_id": content_id,
        "creator_id": creator_id,
        "status": status,
        "attribution": analysis["attribution"],
        "confidence": analysis["confidence"],
        "llm_score": analysis["signals"]["llm"]["score"],
        "llm_source": analysis["signals"]["llm"]["source"],
        "stylometric_score": analysis["signals"]["stylometric"]["score"],
        "stylometric_metrics": analysis["signals"]["stylometric"]["metrics"],
        "appeal_filed": False,
    }
    write_audit_entry(audit_entry)

    return jsonify(
        {
            "content_id": content_id,
            "creator_id": creator_id,
            "status": status,
            "attribution": analysis["attribution"],
            "confidence": analysis["confidence"],
            "label": analysis["label"],
            "signals": analysis["signals"],
        }
    )


@app.post("/appeal")
def appeal():
    payload = request.get_json(silent=True) or {}
    content_id = str(payload.get("content_id", "")).strip()
    creator_reasoning = str(payload.get("creator_reasoning", "")).strip()

    if not content_id:
        return jsonify({"error": "content_id is required"}), 400
    if not creator_reasoning:
        return jsonify({"error": "creator_reasoning is required"}), 400
    if content_id not in CONTENT_STORE:
        return jsonify({"error": "content_id not found in active content store"}), 404

    appeal_record = {
        "timestamp": utc_now(),
        "creator_reasoning": creator_reasoning,
    }
    CONTENT_STORE[content_id]["status"] = "under_review"
    CONTENT_STORE[content_id]["appeals"].append(appeal_record)
    content = CONTENT_STORE[content_id]
    analysis = content["analysis"]

    audit_entry = {
        "event": "appeal",
        "timestamp": appeal_record["timestamp"],
        "content_id": content_id,
        "creator_id": content["creator_id"],
        "status": "under_review",
        "attribution": analysis["attribution"],
        "confidence": analysis["confidence"],
        "llm_score": analysis["signals"]["llm"]["score"],
        "stylometric_score": analysis["signals"]["stylometric"]["score"],
        "appeal_reasoning": creator_reasoning,
        "appeal_filed": True,
    }
    write_audit_entry(audit_entry)

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Appeal received. The content is now queued for human review.",
            "appeal": appeal_record,
        }
    )


@app.get("/log")
def log():
    limit = request.args.get("limit", default=25, type=int)
    limit = max(1, min(limit, 100))
    return jsonify({"entries": read_audit_entries(limit)})


@app.get("/analytics")
def analytics():
    return jsonify(build_analytics())


if __name__ == "__main__":
    app.run(debug=True)
