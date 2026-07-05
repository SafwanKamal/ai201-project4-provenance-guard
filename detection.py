import json
import math
import os
import re
from statistics import mean, pstdev

from dotenv import load_dotenv

load_dotenv()

AI_MARKERS = {
    "it is important to note",
    "furthermore",
    "moreover",
    "in conclusion",
    "paradigm shift",
    "stakeholders",
    "ethical implications",
    "responsible deployment",
    "plays a crucial role",
    "multifaceted",
    "underscore",
}

HUMAN_MARKERS = {
    "honestly",
    "like",
    "anyway",
    "idk",
    "lol",
    "ok so",
    "kinda",
    "probably",
    "WAY",
    "won't",
}

LABELS = {
    "likely_ai": (
        "Likely AI-generated: Our system found strong signals that this text may "
        "have been generated or heavily assisted by AI. This is not a final judgment; "
        "the creator can appeal if the label is wrong."
    ),
    "likely_human": (
        "Likely human-written: Our system found strong signals that this text appears "
        "to be original human writing. Detection is not perfect, so this label should "
        "be read as helpful context rather than proof."
    ),
    "uncertain": (
        "Attribution uncertain: Our system does not have enough confidence to label "
        "this text as AI-generated or human-written. Readers should avoid making "
        "assumptions, and the creator may provide more context."
    ),
}


def split_sentences(text):
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    return sentences or ([text.strip()] if text.strip() else [])


def tokenize(text):
    return re.findall(r"[A-Za-z']+", text.lower())


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def fallback_llm_signal(text):
    """Deterministic proxy for an LLM holistic judgment when no API key is available."""
    lowered = text.lower()
    words = tokenize(text)
    sentences = split_sentences(text)
    marker_score = sum(1 for marker in AI_MARKERS if marker in lowered) * 0.075
    human_marker_penalty = sum(1 for marker in HUMAN_MARKERS if marker.lower() in lowered) * 0.08
    avg_sentence_length = mean([len(tokenize(sentence)) for sentence in sentences]) if sentences else 0
    formal_length_score = clamp((avg_sentence_length - 12) / 22) * 0.22
    contraction_penalty = 0.08 if re.search(r"\b\w+'\w+\b", text) else 0
    all_caps_penalty = 0.08 if re.search(r"\b[A-Z]{2,}\b", text) else 0
    short_text_uncertainty = 0.08 if len(words) < 35 else 0

    score = 0.5 + marker_score + formal_length_score - human_marker_penalty - contraction_penalty - all_caps_penalty
    score = (score * (1 - short_text_uncertainty)) + (0.5 * short_text_uncertainty)
    return {
        "score": round(clamp(score), 3),
        "rationale": "Local fallback estimated holistic AI-likeness from formal phrasing, sentence style, and conversational markers.",
        "source": "local_fallback",
    }


def groq_llm_signal(text):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return fallback_llm_signal(text)

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        prompt = (
            "Classify whether this text appears AI-generated or human-written. "
            "Return only JSON with keys score and rationale. score must be a number "
            "from 0 to 1 where 1 means very likely AI-generated and 0 means very likely human-written.\n\n"
            f"Text:\n{text}"
        )
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a careful provenance classifier that communicates uncertainty."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        payload = json.loads(completion.choices[0].message.content)
        return {
            "score": round(clamp(float(payload.get("score", 0.5))), 3),
            "rationale": str(payload.get("rationale", "No rationale returned.")),
            "source": "groq",
        }
    except Exception as exc:
        fallback = fallback_llm_signal(text)
        fallback["rationale"] = f"Groq unavailable; used fallback. Fallback rationale: {fallback['rationale']}"
        fallback["source"] = "local_fallback_after_groq_error"
        fallback["error"] = str(exc)
        return fallback


def stylometric_signal(text):
    words = tokenize(text)
    sentences = split_sentences(text)
    if not words:
        return {
            "score": 0.5,
            "metrics": {
                "type_token_ratio": 0,
                "sentence_length_stdev": 0,
                "punctuation_density": 0,
                "avg_sentence_length": 0,
            },
            "rationale": "No text tokens were available, so the stylometric signal stayed uncertain.",
        }

    sentence_lengths = [len(tokenize(sentence)) for sentence in sentences]
    avg_sentence_length = mean(sentence_lengths)
    length_stdev = pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0
    type_token_ratio = len(set(words)) / len(words)
    punctuation_density = len(re.findall(r"[!?;:,-]", text)) / max(len(words), 1)

    uniformity_score = 1 - clamp(length_stdev / 12)
    vocabulary_score = clamp((0.72 - type_token_ratio) / 0.42)
    polish_score = clamp((avg_sentence_length - 10) / 18)
    punctuation_score = 1 - clamp(punctuation_density / 0.22)

    score = (
        uniformity_score * 0.35
        + vocabulary_score * 0.25
        + polish_score * 0.25
        + punctuation_score * 0.15
    )

    return {
        "score": round(clamp(score), 3),
        "metrics": {
            "type_token_ratio": round(type_token_ratio, 3),
            "sentence_length_stdev": round(length_stdev, 3),
            "punctuation_density": round(punctuation_density, 3),
            "avg_sentence_length": round(avg_sentence_length, 3),
        },
        "rationale": "Stylometry measured sentence uniformity, vocabulary diversity, average sentence length, and punctuation density.",
    }


def combine_scores(llm_score, stylometric_score):
    raw = (llm_score * 0.7) + (stylometric_score * 0.3)
    disagreement = abs(llm_score - stylometric_score)
    if disagreement > 0.3:
        raw = (raw * 0.9) + (0.5 * 0.1)
    return round(clamp(raw), 3)


def attribution_from_confidence(confidence):
    if confidence >= 0.7:
        return "likely_ai"
    if confidence <= 0.3:
        return "likely_human"
    return "uncertain"


def label_for_attribution(attribution):
    return LABELS[attribution]


def analyze_text(text):
    llm = groq_llm_signal(text)
    stylometry = stylometric_signal(text)
    confidence = combine_scores(llm["score"], stylometry["score"])
    attribution = attribution_from_confidence(confidence)
    return {
        "attribution": attribution,
        "confidence": confidence,
        "label": label_for_attribution(attribution),
        "signals": {
            "llm": llm,
            "stylometric": stylometry,
        },
    }
