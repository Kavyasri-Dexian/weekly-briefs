"""
Grounded narration via an open-source model, with a hard numeric gate in
front of publication.

Why a gate at all: an LLM reading the fact sheet can still restate a number
wrong, round it differently, or invent a plausible-sounding figure. The
previous version of this pipeline sidestepped that risk entirely by using a
fixed template (see pipeline.py's narrate_english/narrate_hindi) that simply
cannot state an unsupported number. This module keeps that guarantee while
adding real generative fluency: every model draft is checked — every number
it contains must appear in the fact sheet it was given — and any draft that
fails the check is retried, then discarded in favor of the deterministic
template. The template is therefore still the safety net, never removed.

Two providers, selected by NARRATION_PROVIDER:
- "local" (default): runs a small open-source model entirely on this
  machine via local_infer.py in an isolated venv (C:\\venv\\mlenv — created
  to dodge a Windows long-path pip install failure in the main environment).
  No account, no token, no cost — the tradeoff is model size/quality and
  real memory pressure on a RAM-constrained machine.
- "hf": Hugging Face's hosted Inference API. Requires an HF_TOKEN env var
  (a free token from https://huggingface.co/settings/tokens) and, in
  practice, paid credits — HF's free tier does not currently serve any
  capable chat model (verified directly: Qwen2.5-7B/1.5B, Mistral-7B,
  Gemma-2-2B, Phi-3-mini, and SmolLM2-1.7B all rejected with "not supported
  by provider hf-inference" or required Inference Providers billing).

Either way, any failure (missing dependency, OOM, timeout, no token,
network) falls back to the template with no retries wasted.
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter

NARRATION_PROVIDER = os.environ.get("NARRATION_PROVIDER", "local")
DEFAULT_MODEL = os.environ.get("HF_NARRATION_MODEL", "Qwen/Qwen2.5-7B-Instruct")
LOCAL_PYTHON = os.environ.get("LOCAL_PYTHON", r"C:\venv\mlenv\Scripts\python.exe")
LOCAL_MODEL = os.environ.get("LOCAL_NARRATION_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")


def _lora_adapter_path(language: str) -> str:
    """Per-language LoRA adapter saved by train_lora.py (see that script for
    what it's trained on — self-distillation from the deterministic
    template using build_training_data.py's historical-week examples).
    Loaded automatically if present; falls back to the plain base model
    silently if not (e.g. before the first training run) — this function
    only returns a path, _call_local_model checks it actually exists."""
    override = os.environ.get(f"LOCAL_LORA_ADAPTER_{language.upper()}")
    if override:
        return override
    return os.path.join(os.path.dirname(__file__), "..", f"lora_adapter_{language}")
LOCAL_TIMEOUT_SECONDS = int(os.environ.get("LOCAL_NARRATION_TIMEOUT", "360"))
LOCAL_MAX_NEW_TOKENS = int(os.environ.get("LOCAL_MAX_NEW_TOKENS", "250"))  # a 5-8 bullet summary doesn't need 400+
MAX_ATTEMPTS = 3  # 1 initial draft + 2 corrective retries before falling back to the template
MIN_NUMBERS_EXPECTED = 10  # was 15, tuned against the old bullet-list narrative format (~40+
# numbers). After the redesign trimmed the prompt to 3 tightly-scoped paragraphs, a genuinely
# good draft can legitimately land in the 12-20 range depending on how many gainers/decliners
# qualify that week — a live run was seen rejecting a valid 14-number draft at the old floor.
# 10 still reliably catches the real failure modes this exists for (refusals and empty
# non-answers cite 0-3 numbers at most) without false-rejecting thin-but-correct summaries.
MIN_SENTENCES = 6  # a real 3-paragraph grounded summary always has well over this many sentences


_MARKDOWN_RE = re.compile(r"(^#{1,6}\s|\*\*[^*]+\*\*|^\s*[-*•]\s)", re.MULTILINE)


def _looks_like_prose_summary(draft: str, min_sentences: int = None):
    """Catches failure modes the numeric floor alone misses. Two are drafts
    that trivially pass the numeric gate without being an actual summary:
    a model echoing the input JSON verbatim (every number in it "matches"
    the source because it IS the source), and one too short to be a real
    3-paragraph summary (a refusal or one-line non-answer). The third —
    added after a real greedy-decoding test produced "### Executive
    Narrative" / "**3%**" markdown headers and bold instead of the required
    flowing prose paragraphs, which nothing here previously caught — is
    Markdown structure: the prompt explicitly forbids headings/bullets/list
    formatting, and a draft using them anyway isn't the requested output
    even when every number in it happens to be correct."""
    stripped = draft.strip()
    if "```" in draft or stripped.startswith("{") or stripped.startswith("["):
        return False, "draft looks like raw JSON/code, not prose"
    if _MARKDOWN_RE.search(draft):
        return False, "draft uses markdown headings/bold/bullets, not plain prose paragraphs"
    min_sentences = MIN_SENTENCES if min_sentences is None else min_sentences
    sentence_count = len(re.findall(r"[.!?।](?:\s|$)", draft))
    if sentence_count < min_sentences:
        return False, f"only {sentence_count} sentences found (expected >= {min_sentences})"
    return True, None

PROMPT_INSTRUCTIONS = {
    "en": (
        "You are a data-to-text summarizer for an Indian agricultural mandi (market) report. "
        "You are given a JSON fact sheet of verified statistics for Madhya Pradesh's weekly mandi "
        "prices and arrivals. Write the body of an executive narrative as exactly 3 short flowing "
        "paragraphs of prose, in English, separated by a single blank line.\n\n"
        "Rules — follow exactly:\n"
        "1. Use ONLY numbers that appear verbatim in the JSON below. Do not calculate, estimate, "
        "round differently, or invent any figure not already present in the JSON.\n"
        "2. Copy every number EXACTLY as printed in the JSON, digit for digit, including the "
        "decimal point. If the JSON says 0.3, you must write 0.3 — never 3, never 0.30, never "
        "round it. A JSON value of 0.3 is not the same number as 3, even though they look similar; "
        "treat every digit before AND after the decimal point as significant.\n"
        "3. Do not include a title, date range, or heading — only the 3 paragraphs.\n"
        "4. Do NOT use bullet points, dashes, Markdown headings (#, ##), Markdown bold (**text**), "
        "or any list/markup formatting of any kind — plain prose sentences only, no symbols other "
        "than normal punctuation. Do NOT copy the wording of the example sentence in rule 5 below; "
        "it exists only to show sentence STYLE, and its numbers are placeholders, not real data.\n"
        "5. Write complete, grammatical sentences joined into paragraphs — for example, a sentence "
        "shaped like 'Total arrivals rose [X]% week-on-week to [Y] tonnes' with X and Y replaced by "
        "the JSON's own arrivals figures, NOT a 'Label: value' fragment like 'Week-on-week change: X%'.\n"
        "6. Paragraph 1: total arrivals and its week-on-week change, the top traded commodity and "
        "its share, and other leading commodities. Paragraph 2: the largest price gainers and "
        "decliners, and for the top commodity, how this week's average price compares to last "
        "week, the same week last month, and the same week last year (price_trend in the JSON). "
        "Paragraph 3: market reporting compliance — how many markets reported, the top reporting "
        "market, how many reported 5-6 days and how many filed no return.\n"
        "7. Output ONLY the 3 paragraphs — no preamble, no closing remarks, no headings."
    ),
    "hi": (
        "आप एक भारतीय कृषि मंडी रिपोर्ट के लिए डेटा-से-पाठ सारांशकर्ता हैं। आपको मध्य प्रदेश की "
        "साप्ताहिक मंडी कीमतों और आवक के सत्यापित आंकड़ों वाली एक JSON फैक्ट शीट दी गई है। हिंदी में "
        "कार्यकारी नैरेटिव का मुख्य भाग ठीक 3 संक्षिप्त प्रवाहमान अनुच्छेदों में लिखें, प्रत्येक "
        "अनुच्छेद के बीच एक खाली पंक्ति छोड़ें।\n\n"
        "नियम — बिल्कुल पालन करें:\n"
        "1. केवल वही संख्याएँ उपयोग करें जो नीचे दिए गए JSON में ज्यों की त्यों मौजूद हैं। कोई गणना, "
        "अनुमान, भिन्न पूर्णांकन, या नई संख्या न बनाएं।\n"
        "2. JSON में लिखी हर संख्या को अंक-दर-अंक बिल्कुल वैसे ही लिखें, दशमलव बिंदु सहित। यदि JSON में "
        "0.3 लिखा है, तो 0.3 ही लिखें — न 3, न 0.30, न कोई पूर्णांकित रूप। 0.3 और 3 दो अलग-अलग संख्याएँ "
        "हैं, भले ही देखने में मिलती-जुलती लगें; दशमलव बिंदु से पहले और बाद के हर अंक को महत्वपूर्ण मानें।\n"
        "3. कोई शीर्षक या दिनांक सीमा शामिल न करें — केवल 3 अनुच्छेद।\n"
        "4. बुलेट पॉइंट, डैश, Markdown शीर्षक (#, ##), Markdown बोल्ड (**पाठ**), या किसी भी प्रकार की "
        "सूची/मार्कअप फॉर्मेटिंग का उपयोग न करें — केवल सामान्य विराम चिह्नों वाले सादे गद्य वाक्य। नीचे "
        "नियम 5 के उदाहरण वाक्य के शब्दों की नकल न करें; यह केवल वाक्य-शैली दिखाने के लिए है, इसकी "
        "संख्याएँ केवल प्लेसहोल्डर हैं, वास्तविक डेटा नहीं।\n"
        "5. पूर्ण, व्याकरणिक वाक्यों में लिखें (कर्ता और क्रिया सहित) — जैसे 'इस सप्ताह कुल आवक [X]% "
        "बढ़कर [Y] टन हो गई' जिसमें X और Y की जगह JSON के अपने आवक आंकड़े हों, न कि 'साप्ताहिक परिवर्तन: "
        "X%' जैसा खंड।\n"
        "6. अनुच्छेद 1: कुल आवक और उसका साप्ताहिक परिवर्तन, सबसे अधिक कारोबार वाली वस्तु और उसकी "
        "हिस्सेदारी, तथा अन्य प्रमुख वस्तुएँ। अनुच्छेद 2: सबसे बड़ी मूल्य वृद्धि और गिरावट, और सबसे अधिक "
        "कारोबार वाली वस्तु के लिए इस सप्ताह का औसत मूल्य पिछले सप्ताह, पिछले महीने के इसी सप्ताह, और "
        "पिछले वर्ष के इसी सप्ताह की तुलना में कैसा रहा (JSON में price_trend)। अनुच्छेद 3: मंडी "
        "रिपोर्टिंग अनुपालन — कितनी मंडियों ने रिपोर्ट की, सबसे अधिक रिपोर्ट करने वाली मंडी, कितनी "
        "मंडियों ने 5-6 दिन रिपोर्ट की और कितनी ने कोई रिपोर्ट दर्ज नहीं की।\n"
        "7. केवल 3 अनुच्छेद आउटपुट करें — कोई भूमिका, शीर्षक या समापन टिप्पणी नहीं।\n\n"
        "कृषि शब्दावली: गेहूँ=Wheat, मंडी=Mandi, आवक=Arrivals, मोडल मूल्य=Modal Price, "
        "क्विंटल=Quintal, टन=Tonnes — इन्हीं शब्दों का प्रयोग करें।"
    ),
}


def _slim_fact_sheet(fs: dict) -> dict:
    """Only the numeric/statistical content — strips free-text fields (source,
    caveats, generated_at) AND methodology/config numbers (e.g.
    min_trading_days_for_ranking=3) that aren't reportable facts. Excluding
    the latter matters for the gate, not just prompt hygiene: a real failure
    caught in testing had the model write "week-on-week change: 3%" for an
    actual change of 0.3%, and the gate passed it — not because of the small-
    integer leniency, but because min_trading_days_for_ranking genuinely
    equals 3 elsewhere in the JSON, and the gate only checks "does this
    number appear anywhere," not "is it attached to the claim it's being
    used for." Removing non-factual numbers from the pool is a direct,
    targeted fix for that hole — it does not add context-binding in general
    (still a real, documented limitation), it just stops config values from
    being usable as cover for an unrelated wrong number."""
    top_commodities = dict(fs["top_commodities"])
    # Trimmed to what the narration prompt actually asks for — "the top
    # traded commodity" plus "other leading commodities" (up to 4 more) — the
    # remaining entries up to TOP_N_COMMODITIES exist for the UI table, not
    # for narration. This must match what build_training_data.py trains on;
    # they share this function specifically so the two can never drift apart.
    top_commodities["top_commodities"] = top_commodities["top_commodities"][:5]
    # concentration_hhi/donut_slices back the UI's donut chart only — the
    # narrative prompt never asks about commodity concentration, so this
    # shallow copy of fs["top_commodities"] must not carry them through.
    top_commodities.pop("concentration_hhi", None)
    top_commodities.pop("donut_slices", None)

    price_trend = {k: v for k, v in fs.get("price_trend", {}).items() if k != "definition"}
    if "commodities" in price_trend:
        # Only ever narrates the single top commodity's trend.
        price_trend["commodities"] = price_trend["commodities"][:1]

    return {
        "state": fs["state"],
        "overall_arrivals": fs["overall_arrivals"],
        "market_compliance": {
            # compliance_bands duplicates markets_reporting_5_to_6_days etc. as a
            # per-band array (1-2 days, 3-4 days, ...) — leaving it in gives the
            # model closely-related-but-wrong numbers (e.g. the 1-2-day band's
            # count) that still pass grounding, a real failure caught in testing
            # ("17 reports on 5-6 days" when the real 5-6-day count is 186, 17
            # being the UNRELATED 1-2-day band's count from this same array).
            k: v for k, v in fs["market_compliance"].items()
            if k not in ("roster_caveat", "compliance_bands")
        },
        "top_commodities": top_commodities,
        "price_change": {
            k: v for k, v in fs["price_change"].items()
            if k not in ("reason", "min_trading_days_for_ranking", "commodities_excluded_thin_trade")
        },
        "price_trend": price_trend,
    }


# Per-paragraph slices of _slim_fact_sheet, each carrying ONLY the numbers
# that paragraph's prompt asks for (~4-15 numbers vs. the full task's
# ~20-40+) — see narrate_paragraph_with_model for why this exists. Field
# selection mirrors pipeline.py's narrate_english/narrate_hindi templates
# exactly (paragraph 1 = arrivals + top commodities, paragraph 2 = price
# moves + trend, paragraph 3 = compliance), so a paragraph's prompt can
# never legitimately need a number this slice omits.
def _slim_fact_sheet_p1(fs: dict) -> dict:
    ranked = fs["top_commodities"]["top_commodities"][:5]
    trimmed = [{"commodity": ranked[0]["commodity"], "arrival_value": ranked[0]["arrival_value"],
                "share_pct_of_state_arrivals": ranked[0]["share_pct_of_state_arrivals"],
                "markets_trading": ranked[0]["markets_trading"]}] if ranked else []
    trimmed += [{"commodity": r["commodity"], "arrival_value": r["arrival_value"]} for r in ranked[1:5]]
    return {"state": fs["state"], "overall_arrivals": fs["overall_arrivals"], "top_commodities": trimmed}


def _slim_fact_sheet_p2(fs: dict) -> dict:
    price_change = {
        k: v for k, v in fs["price_change"].items()
        if k not in ("reason", "min_trading_days_for_ranking", "commodities_excluded_thin_trade")
    }
    price_trend = {k: v for k, v in fs.get("price_trend", {}).items() if k != "definition"}
    if "commodities" in price_trend:
        price_trend["commodities"] = price_trend["commodities"][:1]
    return {"state": fs["state"], "price_change": price_change, "price_trend": price_trend}


def _slim_fact_sheet_p3(fs: dict) -> dict:
    return {
        "state": fs["state"],
        "market_compliance": {
            k: v for k, v in fs["market_compliance"].items()
            if k not in ("roster_caveat", "compliance_bands")
        },
    }


PARAGRAPH_PROMPT_INSTRUCTIONS = {
    "en": {
        1: (
            "You are a data-to-text summarizer for an Indian agricultural mandi (market) report. "
            "Write EXACTLY ONE short paragraph (2-4 sentences) of plain prose, in English, covering: "
            "total arrivals across Madhya Pradesh and its week-on-week change (overall_arrivals in the "
            "JSON below), the top traded commodity and its share of state arrivals, and the other "
            "leading commodities by arrival volume (top_commodities in the JSON).\n\n"
            "Rules — follow exactly:\n"
            "1. Use ONLY numbers that appear verbatim in the JSON below, copied exactly digit for "
            "digit including the decimal point. A JSON value of 0.3 is not the same as 3 — never "
            "round, shift, or invent a number.\n"
            "2. No title, heading, bullet points, dashes, or Markdown formatting (no #, no **) — "
            "plain prose sentences only.\n"
            "3. Output ONLY the one paragraph — no preamble, no closing remarks."
        ),
        2: (
            "You are a data-to-text summarizer for an Indian agricultural mandi (market) report. "
            "Write EXACTLY ONE short paragraph (2-4 sentences) of plain prose, in English, covering: "
            "the largest week-on-week price gainers and decliners (price_change in the JSON below), "
            "and for the top commodity, how this week's average price compares to last week, the same "
            "week last month, and the same week last year (price_trend in the JSON).\n\n"
            "Rules — follow exactly:\n"
            "1. Use ONLY numbers that appear verbatim in the JSON below, copied exactly digit for "
            "digit including the decimal point. A JSON value of 0.3 is not the same as 3 — never "
            "round, shift, or invent a number.\n"
            "2. No title, heading, bullet points, dashes, or Markdown formatting (no #, no **) — "
            "plain prose sentences only.\n"
            "3. Output ONLY the one paragraph — no preamble, no closing remarks."
        ),
        3: (
            "You are a data-to-text summarizer for an Indian agricultural mandi (market) report. "
            "Write EXACTLY ONE short paragraph (2-4 sentences) of plain prose, in English, covering "
            "market reporting compliance: how many of the registered market yards reported at least "
            "once, how many reported on all 7 days, how many reported on 5-6 days, how many filed no "
            "return, and which market reported the most days (market_compliance in the JSON below).\n\n"
            "Rules — follow exactly:\n"
            "1. Use ONLY numbers that appear verbatim in the JSON below, copied exactly digit for "
            "digit.\n"
            "2. No title, heading, bullet points, dashes, or Markdown formatting (no #, no **) — "
            "plain prose sentences only.\n"
            "3. Output ONLY the one paragraph — no preamble, no closing remarks."
        ),
    },
    "hi": {
        1: (
            "आप एक भारतीय कृषि मंडी रिपोर्ट के लिए डेटा-से-पाठ सारांशकर्ता हैं। हिंदी में ठीक एक "
            "संक्षिप्त अनुच्छेद (2-4 वाक्य) सादे गद्य में लिखें, जिसमें शामिल हो: मध्य प्रदेश की कुल आवक "
            "और उसका साप्ताहिक परिवर्तन (नीचे JSON में overall_arrivals), सबसे अधिक कारोबार वाली वस्तु "
            "और उसकी राज्य आवक में हिस्सेदारी, तथा अन्य प्रमुख वस्तुएँ (top_commodities)।\n\n"
            "नियम — बिल्कुल पालन करें:\n"
            "1. केवल वही संख्याएँ उपयोग करें जो नीचे JSON में ज्यों की त्यों मौजूद हैं, दशमलव बिंदु सहित "
            "अंक-दर-अंक। JSON में 0.3 का मतलब 3 नहीं है — कभी पूर्णांकित, स्थानांतरित या नई संख्या न बनाएं।\n"
            "2. कोई शीर्षक, बुलेट पॉइंट, डैश, या Markdown फॉर्मेटिंग (#, **) नहीं — केवल सादे गद्य वाक्य।\n"
            "3. केवल वह एक अनुच्छेद आउटपुट करें — कोई भूमिका या समापन टिप्पणी नहीं।"
        ),
        2: (
            "आप एक भारतीय कृषि मंडी रिपोर्ट के लिए डेटा-से-पाठ सारांशकर्ता हैं। हिंदी में ठीक एक "
            "संक्षिप्त अनुच्छेद (2-4 वाक्य) सादे गद्य में लिखें, जिसमें शामिल हो: सबसे बड़ी साप्ताहिक मूल्य "
            "वृद्धि और गिरावट (नीचे JSON में price_change), और सबसे अधिक कारोबार वाली वस्तु के लिए इस "
            "सप्ताह का औसत मूल्य पिछले सप्ताह, पिछले महीने के इसी सप्ताह, और पिछले वर्ष के इसी सप्ताह की "
            "तुलना में कैसा रहा (price_trend)।\n\n"
            "नियम — बिल्कुल पालन करें:\n"
            "1. केवल वही संख्याएँ उपयोग करें जो नीचे JSON में ज्यों की त्यों मौजूद हैं, दशमलव बिंदु सहित "
            "अंक-दर-अंक। JSON में 0.3 का मतलब 3 नहीं है — कभी पूर्णांकित, स्थानांतरित या नई संख्या न बनाएं।\n"
            "2. कोई शीर्षक, बुलेट पॉइंट, डैश, या Markdown फॉर्मेटिंग (#, **) नहीं — केवल सादे गद्य वाक्य।\n"
            "3. केवल वह एक अनुच्छेद आउटपुट करें — कोई भूमिका या समापन टिप्पणी नहीं।"
        ),
        3: (
            "आप एक भारतीय कृषि मंडी रिपोर्ट के लिए डेटा-से-पाठ सारांशकर्ता हैं। हिंदी में ठीक एक "
            "संक्षिप्त अनुच्छेद (2-4 वाक्य) सादे गद्य में लिखें, जिसमें मंडी रिपोर्टिंग अनुपालन शामिल हो: "
            "कितनी पंजीकृत मंडियों ने कम से कम एक बार रिपोर्ट की, कितनी ने सभी 7 दिन रिपोर्ट की, कितनी "
            "ने 5-6 दिन रिपोर्ट की, कितनी ने कोई रिपोर्ट दर्ज नहीं की, और किस मंडी ने सबसे अधिक दिन "
            "रिपोर्ट की (नीचे JSON में market_compliance)।\n\n"
            "नियम — बिल्कुल पालन करें:\n"
            "1. केवल वही संख्याएँ उपयोग करें जो नीचे JSON में ज्यों की त्यों मौजूद हैं, अंक-दर-अंक।\n"
            "2. कोई शीर्षक, बुलेट पॉइंट, डैश, या Markdown फॉर्मेटिंग (#, **) नहीं — केवल सादे गद्य वाक्य।\n"
            "3. केवल वह एक अनुच्छेद आउटपुट करें — कोई भूमिका या समापन टिप्पणी नहीं।"
        ),
    },
}

_PARAGRAPH_SLIM_BUILDERS = {1: _slim_fact_sheet_p1, 2: _slim_fact_sheet_p2, 3: _slim_fact_sheet_p3}
_PARAGRAPH_MIN_NUMBERS = {1: 4, 2: 6, 3: 4}


def narrate_paragraph_with_model(fact_sheet: dict, language: str, paragraph: int, model: str = None):
    """Generates ONE paragraph at a time instead of the full 3-paragraph
    narrative in one model call — see narrate_with_model's docstring for
    the evidence behind this. Each call is gated exactly like the full-task
    path (numeric grounding + prose-shape + spelling/grammar), just against
    a slice of the fact sheet ~3-10x smaller. Returns (paragraph_text_or_
    None, meta_dict) — same contract as narrate_with_model."""
    slim = _PARAGRAPH_SLIM_BUILDERS[paragraph](fact_sheet)
    instructions = PARAGRAPH_PROMPT_INSTRUCTIONS[language][paragraph]
    return narrate_with_model(
        fact_sheet, language, model=model,
        slim=slim, instructions=instructions,
        min_numbers_expected=_PARAGRAPH_MIN_NUMBERS[paragraph], min_sentences=1,
    )


def _walk_numbers(obj, out: set):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(round(float(obj), 2))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_numbers(v, out)


# (?<!\d) blocks a hyphen that's actually attached to a preceding digit (a
# range like "5-6 days") from being misread as a minus sign — without it,
# "5-6" parsed as two numbers [5, -6], and -6 would fail the gate as
# "unsupported" even in fully correct, 100%-grounded template text (the same
# failure mode as the earlier ISO-date fix, "2026-07-14" -> [2026, -7, -14],
# but here it's a real, ongoing false-positive risk rather than a one-off —
# any range phrase anywhere in either language template can trigger it).
_NUMBER_RE = re.compile(r"(?<!\d)-?\d[\d,]*\.?\d*")


def _decimal_shift_hints(unsupported: list, allowed_numbers: set) -> list:
    """A real, observed failure mode (not hypothetical): a small local model
    writing "3" for a real value of "0.3" — a decimal-point shift, not a
    random hallucination. It's specifically detectable: the wrong number is
    exactly the real one times/divided by a power of 10. When found, this
    hands the model the actual correct value directly in the retry prompt
    instead of only saying "that number is wrong" and leaving it to guess
    again — self-correction from a bare rejection message alone has been
    observed to fail repeatedly on this exact case even across retries."""
    hints = []
    for wrong in unsupported:
        if wrong == 0:
            continue
        for shift in (0.001, 0.01, 0.1, 10, 100, 1000):
            candidate = round(wrong * shift, 4)
            match = next((n for n in allowed_numbers if abs(n - candidate) < 0.005), None)
            if match is not None:
                hints.append(f"{wrong} should be {match} (you likely shifted the decimal point)")
                break
    return hints


def extract_numbers(text: str):
    """Returns [(value, is_percent), ...]. is_percent is True when the number
    is immediately followed by '%' — percentages are always a specific claim
    (a week-on-week change, a share), never structural/ordinal language, so
    the caller must never apply the small-integer leniency to one. This
    distinction exists because of a real failure caught in testing: a model
    wrote "3%" for an actual change of "0.3%" and the gate let it through,
    since 3 fell inside the old blanket 0-10 "ordinal" allowance — a wrong
    number that happened to be small still passed. Percentages now bypass
    that allowance entirely and must match a real fact-sheet value."""
    found = []
    for match in _NUMBER_RE.finditer(text):
        cleaned = match.group().replace(",", "")
        try:
            value = round(float(cleaned), 2)
        except ValueError:
            continue
        tail = text[match.end():match.end() + 1]
        found.append((value, tail == "%"))
    return found


def check_numeric_grounding(draft: str, fact_sheet_slim: dict):
    """Returns (ok: bool, unsupported: list[float]). Small integers (0-10) are
    allowed ONLY when not attached to a '%' — they cover structural language
    ("top 3", "5-6 days") rather than facts the model could get wrong. A
    percentage is always a specific claim and must match a value actually
    present in the fact sheet, within float-rounding tolerance, regardless of
    how small it is.

    Both signs of every allowed magnitude are accepted: a decline stored as
    pct_change=-41.47 is equally correctly reported as "fell 41.47%" (positive
    prose) or "-41.47%" (signed prose) — the magnitude is what must be
    grounded. This gate does NOT verify that the model paired the right sign
    with the right direction word (e.g. calling a decline a "gain") — that is
    a distinct, non-numeric error class the plan leaves to HHEM-style
    grounding checks / human review, not this gate."""
    allowed = set()
    _walk_numbers(fact_sheet_slim, allowed)
    allowed |= {-v for v in allowed}
    structural_ok = {float(i) for i in range(0, 11)}

    numbers = extract_numbers(draft)
    unsupported = []
    for n, is_percent in numbers:
        if n in allowed:
            continue
        # tolerate a rounding step the model might apply on its own
        if any(abs(n - a) < 0.05 for a in allowed):
            continue
        if not is_percent and n in structural_ok:
            continue
        unsupported.append(n)
    return (len(unsupported) == 0, unsupported, len(numbers))


def check_number_multiplicity(draft: str, fact_sheet_slim: dict):
    """Closes a real gap check_numeric_grounding leaves open: it verifies
    every number in the draft EXISTS somewhere in the source, but not that
    it's attached to the right claim. A live test caught this exact failure
    — a draft correctly grounded market_compliance's 5-to-6-day count as
    186, then reused 186 a second time in place of a DIFFERENT field's real
    value (74, the all-7-days count) — every number in the draft was
    individually real, so check_numeric_grounding passed it, but the
    sentence was factually wrong. This catches over-use: if a value is
    required N times by the source but the draft uses it more than N times,
    something else's real value got dropped in favor of a duplicate.
    Values 0-10 are excluded (same as check_numeric_grounding's
    structural_ok) since small round numbers legitimately repeat as
    day-count band language ("all 7 days", "5-6 days") independent of the
    underlying data's own count — this check is only reliable for the
    larger/decimal values that have no such structural role. Doesn't catch
    every possible swap (e.g. two required values trading places one-for-
    one still balances), but directly closes the one observed in testing."""
    def is_trackable(v):
        return v > 10 or v != int(v)

    required = Counter()

    def walk(o):
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            v = abs(round(float(o), 2))
            if is_trackable(v):
                required[v] += 1
        elif isinstance(o, dict):
            for val in o.values():
                walk(val)
        elif isinstance(o, list):
            for val in o:
                walk(val)

    walk(fact_sheet_slim)

    used = Counter()
    for n, _ in extract_numbers(draft):
        v = abs(n)
        if is_trackable(v):
            used[v] += 1

    over_used = [v for v, count in used.items() if required.get(v, 0) and count > required[v]]
    return (len(over_used) == 0, over_used)


def check_paraphrase_fidelity(original: str, paraphrase: str):
    """Used by narrate_by_paraphrase, not narrate_with_model — a stricter,
    simpler check for a fundamentally different task. narrate_with_model
    generates prose FROM a JSON fact sheet, where the model has to extract
    and correctly attribute ~10-40 numbers itself (the task shown in
    testing to cause sign errors and cross-entity mixing). narrate_by_
    paraphrase instead gives the model an ALREADY-CORRECT template passage
    and asks only for a reworded version — every number is already
    correctly attached to its claim in the input, so the only thing that
    can go wrong is the rewrite adding, dropping, or altering a number.
    Compares the multiset of number MAGNITUDES in each text (not just
    membership) — preserves the multiplicity check's insight that a
    duplicated-in-place-of-a-dropped-one number is exactly as wrong as an
    invented one. Signs are normalized away before comparing, same
    leniency as check_numeric_grounding and for the same reason: "-21.1%"
    and "fell 21.1%" are equally correct prose for the same fact — a real
    test run flagged the second phrasing as a fidelity failure before this
    was added, purely because the literal minus sign was gone, even though
    the paraphrase was accurate. Returns (ok, added: list, dropped: list)."""
    orig_counts = Counter(round(abs(n), 2) for n, _ in extract_numbers(original))
    para_counts = Counter(round(abs(n), 2) for n, _ in extract_numbers(paraphrase))
    added = sorted((para_counts - orig_counts).elements())
    dropped = sorted((orig_counts - para_counts).elements())
    return (not added and not dropped), added, dropped


def score_grounding(text: str, fact_sheet: dict) -> dict:
    """Public entry point for scoring ANY final text (model draft or template
    fallback) against a full (non-slim) fact sheet — used to report an
    accuracy/confidence figure on whatever actually got published, not just
    on model drafts. Every number found in the text is checked; since only
    text that already passed the gate (or the template, which is grounded by
    construction) is ever published, accuracy_pct is 100 by definition for
    the emitted artifact — this exists to make that guarantee visible and
    auditable, not to catch anything new at this point."""
    slim = _slim_fact_sheet(fact_sheet)
    ok, unsupported, total = check_numeric_grounding(text, slim)
    verified = total - len(unsupported)
    return {
        "numbers_checked": total,
        "numbers_verified": verified,
        "accuracy_pct": round(verified / total * 100, 1) if total else 100.0,
        "unsupported": unsupported,
    }


_DOMAIN_GLOSSARY_EN = {
    "mandi", "mandis", "agmarknet", "wow", "hhi", "msp", "qtl", "rs",
    "quintal", "quintals", "tonne", "tonnes", "modal", "arrivals", "yoy",
}


def _proper_noun_vocab(fact_sheet_slim: dict) -> set:
    """Words that will legitimately fail a general-English dictionary check
    but are not spelling errors — market, district and commodity names,
    pulled straight from this week's own fact sheet rather than a fixed
    list, so any real Agmarknet name (however unusual) is automatically
    exempt without maintaining a name list by hand."""
    words = set()

    def collect(value):
        if isinstance(value, str):
            for token in re.findall(r"[A-Za-z]+", value):
                words.add(token.lower())
        elif isinstance(value, dict):
            for v in value.values():
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)

    collect(fact_sheet_slim.get("top_commodities"))
    # price_change's gainers/decliners commonly include commodities outside
    # the top-5-by-arrival list above (e.g. a low-volume spice with a big
    # price swing) — a real fact sheet was seen publishing "Asgand"/"Amla"
    # names that only appear here, incorrectly flagged as misspellings
    # before this was added.
    collect(fact_sheet_slim.get("price_change"))
    collect(fact_sheet_slim.get("price_trend"))
    collect(fact_sheet_slim.get("market_compliance", {}).get("top_reporting_market"))
    collect(fact_sheet_slim.get("state"))
    return words


def check_spelling(draft: str, fact_sheet_slim: dict = None, extra_vocab: set = None):
    """English-only spell check (see module docstring note below on why
    Hindi is excluded) using a local, offline dictionary (pyspellchecker —
    no network call, so this can't leak fact-sheet content externally the
    way a hosted grammar API would). Returns a list of words judged
    misspelled after excluding: numbers/punctuation, short tokens (<=2
    letters, mostly units/initialisms), the fixed domain glossary, and any
    proper noun pulled from this week's own fact sheet (or from
    extra_vocab, for callers like narrate_by_paraphrase that don't have a
    fact_sheet_slim to derive names from)."""
    from spellchecker import SpellChecker

    checker = SpellChecker(distance=1)
    allowed = _DOMAIN_GLOSSARY_EN | (extra_vocab or set())
    if fact_sheet_slim is not None:
        allowed |= _proper_noun_vocab(fact_sheet_slim)
    words = re.findall(r"[A-Za-z]+", draft)
    candidates = {
        w.lower() for w in words
        if len(w) > 2 and w.lower() not in allowed
    }
    return sorted(checker.unknown(candidates))


def check_grammar_heuristics(draft: str, language: str = "en"):
    """Cheap, structural checks — not a real grammar model (none is
    available offline for Hindi, and a hosted one would mean sending
    fact-sheet-derived text to a third party), but enough to catch the
    mechanical slip-ups a small local model actually produces in practice:
    doubled words/spaces, unclosed brackets, a sentence that doesn't end in
    terminal punctuation. Returns a list of issue strings."""
    issues = []
    if re.search(r"[ ]{2,}", draft):  # literal spaces only — \s{2,} false-positives on the
        issues.append("double space")  # blank line ("\n\n") that legitimately separates paragraphs
    if language != "hi" and re.search(r"\b(\w+)\s+\1\b", draft, flags=re.IGNORECASE):
        # Skipped for Hindi: Python's \b/\w word-boundary matching doesn't
        # segment Devanagari conjunct consonants/matras correctly, and a
        # real template run produced a false "क क" repeated-word match from
        # this alone — not a reliable check for this script without a
        # proper Unicode grapheme-cluster segmenter.
        issues.append("repeated word")
    if draft.count("(") != draft.count(")"):
        issues.append("unbalanced parentheses")
    stripped = draft.strip()
    if stripped and stripped[-1] not in ".!?।":
        issues.append("missing terminal punctuation")
    return issues


def check_spelling_grammar(draft: str, fact_sheet_slim: dict, language: str):
    """Combined gate used by narrate_with_model. Hindi spell-checking is
    skipped outright rather than run against an English dictionary (which
    would flag every single Devanagari word as unknown) — grammar
    heuristics still apply to both languages. Returns (ok, issues: list[str])."""
    issues = list(check_grammar_heuristics(draft, language=language))
    if language == "en":
        misspelled = check_spelling(draft, fact_sheet_slim)
        if misspelled:
            issues.append(f"possible misspellings: {misspelled}")
    return (not issues), issues


def _call_hf_model(prompt: str, model: str, token: str) -> str:
    from huggingface_hub import InferenceClient

    client = InferenceClient(model=model, token=token)
    completion = client.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.3,
    )
    return completion.choices[0].message.content.strip()


def _call_local_model(prompt: str, model: str, language: str, use_adapter: bool = True, max_new_tokens: int = None) -> str:
    """Runs local_infer.py in the isolated venv as a subprocess — kept out of
    this process entirely so the main pipeline's environment never needs
    torch/transformers installed, and so a model crash/OOM can't take the
    pipeline down with it (a non-zero exit or timeout just raises here, which
    the caller treats the same as any other narration failure: fall back to
    the template). Passes the language's fine-tuned LoRA adapter if one has
    been trained and saved (see train_lora.py) AND use_adapter is True;
    otherwise runs the plain base model. use_adapter=False exists for
    narrate_by_paraphrase: the adapter was fine-tuned specifically for the
    JSON-extraction task (the one shown to cause attribution errors), so
    reusing it for the unrelated paraphrase task risks pulling in the same
    learned habits rather than helping — the plain instruction-tuned base
    model is the more appropriate tool for a generic reword-this task."""
    if not os.path.exists(LOCAL_PYTHON):
        raise RuntimeError(f"local Python not found at {LOCAL_PYTHON} — see backend/scripts/local_infer.py setup")

    args = [
        LOCAL_PYTHON, os.path.join(os.path.dirname(__file__), "local_infer.py"),
        "--model", model, "--max-new-tokens", str(max_new_tokens or LOCAL_MAX_NEW_TOKENS),
    ]
    adapter_path = _lora_adapter_path(language)
    if use_adapter and os.path.isdir(adapter_path):
        args += ["--lora-adapter", adapter_path]

    result = subprocess.run(
        args,
        input=prompt, capture_output=True, text=True, encoding="utf-8",
        timeout=LOCAL_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"local_infer.py exited {result.returncode}: {result.stderr[-500:]}")
    if not result.stdout.strip():
        raise RuntimeError(f"local_infer.py produced no output: {result.stderr[-500:]}")
    return result.stdout.strip()


PARAPHRASE_PROMPT_INSTRUCTIONS = {
    "en": (
        "Rewrite the passage below in different words, in English, keeping exactly the same "
        "meaning, the same 3-paragraph structure, and the same facts. This is critical: do not "
        "add, remove, round, or change ANY number, percentage, price, date, or proper noun "
        "(commodity or market name) — copy every single one of them EXACTLY as written in the "
        "passage, character for character. Only change sentence structure and word choice around "
        "them. Do not use bullet points, dashes, Markdown headings (#, ##), or Markdown bold "
        "(**text**) — plain prose paragraphs only. Output ONLY the rewritten 3 paragraphs, no "
        "preamble, no closing remarks, no headings.\n\nPassage:\n"
    ),
    "hi": (
        "नीचे दिए गए अनुच्छेद को हिंदी में अलग शब्दों में फिर से लिखें, बिल्कुल वही अर्थ, वही 3-अनुच्छेद "
        "संरचना, और वही तथ्य रखते हुए। यह महत्वपूर्ण है: किसी भी संख्या, प्रतिशत, मूल्य, तारीख, या "
        "संज्ञा (वस्तु या मंडी का नाम) को न जोड़ें, न हटाएं, न पूर्णांकित करें, न बदलें — इनमें से हर एक को "
        "बिल्कुल वैसे ही, अक्षर-दर-अक्षर कॉपी करें जैसे अनुच्छेद में लिखा है। केवल इनके आसपास के वाक्य "
        "संरचना और शब्द चयन को बदलें। बुलेट पॉइंट, डैश, Markdown शीर्षक (#, ##), या Markdown बोल्ड "
        "(**पाठ**) का उपयोग न करें — केवल सादे गद्य अनुच्छेद। केवल फिर से लिखे गए 3 अनुच्छेद आउटपुट करें, "
        "कोई भूमिका, समापन टिप्पणी या शीर्षक नहीं।\n\nअनुच्छेद:\n"
    ),
}


def narrate_by_paraphrase(original_body: str, language: str, model: str = None, max_attempts: int = None):
    """Alternative to narrate_with_model — the user's own idea, and a good
    one: instead of generating prose FROM the raw JSON fact sheet (where the
    model has to extract and correctly attribute ~10-40 numbers itself, the
    task testing showed causes sign errors and cross-commodity mixing), this
    hands the model the ALREADY-CORRECT deterministic template body (see
    pipeline.py's narrate_english/narrate_hindi) and asks only for a
    reworded version. Every number is already correctly attached to its
    claim in the input — the model's job becomes pure paraphrase, a task
    small instruction-tuned models are generally far more reliable at than
    structured extraction. Gated on check_paraphrase_fidelity (not a single
    number added/dropped/altered vs. the original), Markdown/prose-shape,
    and grammar (spelling check skipped here — the input is already known-
    correct English/Hindi, so any word the paraphrase introduces is the
    model's own phrasing choice, not a fact-sheet name to validate; proper
    nouns from the original are still whitelisted in case they get echoed
    back). Returns (paraphrase_or_None, meta_dict) — same contract as
    narrate_with_model, plus meta['original'] holding the template input for
    reference."""
    provider = NARRATION_PROVIDER
    if provider == "hf":
        model = model or DEFAULT_MODEL
        if not os.environ.get("HF_TOKEN"):
            return None, {"model": model, "provider": provider, "attempts": 0, "used_model": False, "reason": "HF_TOKEN not set"}
    else:
        model = model or LOCAL_MODEL

    meta = {"model": model, "provider": provider, "attempts": 0, "used_model": False, "reason": None, "original": original_body}
    base_prompt = f"{PARAPHRASE_PROMPT_INSTRUCTIONS[language]}{original_body}"
    prompt = base_prompt
    proper_nouns = {w.lower() for w in re.findall(r"[A-Za-z]+", original_body) if w[0].isupper()}
    last_draft = None
    last_issue = None
    # A paraphrase can't be shorter than the source and still keep every
    # number — the default LOCAL_MAX_NEW_TOKENS (250) was sized for the old
    # bullet-point task and silently truncates a full-length template body
    # mid-sentence, which then shows up as "dropped" numbers in the fidelity
    # check even though the model never actually got a chance to include
    # them. ~2.2 chars/token is conservative for English/Hindi mixed with
    # numerals; +150 gives headroom for paraphrasing naturally running a
    # little longer than the source.
    paraphrase_max_tokens = max(LOCAL_MAX_NEW_TOKENS, int(len(original_body) / 2.2) + 150)
    attempts_budget = max_attempts if max_attempts is not None else MAX_ATTEMPTS

    for attempt in range(1, attempts_budget + 1):
        meta["attempts"] = attempt
        try:
            if provider == "hf":
                draft = _call_hf_model(prompt, model, os.environ.get("HF_TOKEN"))
            else:
                draft = _call_local_model(prompt, model, language, use_adapter=False, max_new_tokens=paraphrase_max_tokens)
        except Exception as exc:  # noqa: BLE001
            meta["reason"] = f"model call failed: {exc}"
            print(f"  [paraphrase:{language}] attempt {attempt} error: {exc}", file=sys.stderr)
            return None, meta

        last_draft = draft
        fidelity_ok, added, dropped = check_paraphrase_fidelity(original_body, draft)
        if not fidelity_ok:
            last_issue = f"numbers added={added}, dropped={dropped}"
            prompt = (
                f"{base_prompt}\n\nYour rewrite changed the numbers — it added {added} and dropped "
                f"{dropped} compared to the original passage. Rewrite again, keeping every single "
                f"number from the original exactly as it was, in the same quantity."
            )
            continue

        prose_ok, prose_reason = _looks_like_prose_summary(draft, min_sentences=MIN_SENTENCES)
        if not prose_ok:
            last_issue = prose_reason
            prompt = f"{base_prompt}\n\nYour rewrite {prose_reason}. Rewrite again as plain prose paragraphs, no markdown."
            continue

        issues = list(check_grammar_heuristics(draft, language=language))
        if language == "en":
            misspelled = check_spelling(draft, extra_vocab=proper_nouns)
            if misspelled:
                issues.append(f"possible misspellings: {misspelled}")
        if issues:
            last_issue = "; ".join(issues)
            prompt = f"{base_prompt}\n\nYour rewrite had these issues: {issues}. Rewrite again, fixing them."
            continue

        meta["used_model"] = True
        meta["reason"] = "passed paraphrase-fidelity + spelling/grammar gate"
        print(f"  [paraphrase:{language}] attempt {attempt}: passed gate", file=sys.stderr)
        return draft, meta

    meta["reason"] = f"failed paraphrase gate after {attempts_budget} attempts: {last_issue}"
    meta["last_rejected_draft"] = last_draft
    return None, meta


def narrate_with_model(
    fact_sheet: dict, language: str, model: str = None,
    slim: dict = None, instructions: str = None,
    min_numbers_expected: int = None, min_sentences: int = None,
):
    """Attempts a grounded model draft (English or Hindi), gated against the
    fact sheet's own numbers. Returns (text_or_None, meta_dict). text is None
    if every attempt failed the gate or the model call — caller should fall
    back to the deterministic template in that case.

    slim/instructions/min_numbers_expected/min_sentences let a caller run
    this same gated retry loop against a SMALLER, single-paragraph slice of
    the fact sheet instead of the full 3-paragraph task — see
    narrate_paragraph_with_model below for why: a 0.5B model asked to pick
    the right ~20-40 numbers out of the full fact sheet and write 3
    paragraphs in one shot was observed (across many real runs) to
    frequently cite a wrong or shifted number somewhere in that large a
    task, even after retraining and explicit correction hints. Scoping each
    call to ~4-15 numbers relevant to ONE paragraph is a fundamentally
    smaller, more tractable task, independent of any further prompt/model
    tuning. Defaults to the original full-task behavior when omitted."""
    provider = NARRATION_PROVIDER
    if provider == "hf":
        token = os.environ.get("HF_TOKEN")
        model = model or DEFAULT_MODEL
        if not token:
            return None, {"model": model, "provider": provider, "attempts": 0, "used_model": False, "reason": "HF_TOKEN not set"}
    else:
        model = model or LOCAL_MODEL

    meta = {"model": model, "provider": provider, "attempts": 0, "used_model": False, "reason": None}

    slim = slim if slim is not None else _slim_fact_sheet(fact_sheet)
    instructions = instructions if instructions is not None else PROMPT_INSTRUCTIONS[language]
    min_numbers_expected = min_numbers_expected if min_numbers_expected is not None else MIN_NUMBERS_EXPECTED
    min_sentences = min_sentences if min_sentences is not None else MIN_SENTENCES
    base_prompt = f"{instructions}\n\nJSON fact sheet:\n{json.dumps(slim, ensure_ascii=False)}"
    prompt = base_prompt
    last_unsupported = []
    last_draft = None
    last_spelling_issues = []
    last_over_used = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        meta["attempts"] = attempt
        try:
            if provider == "hf":
                draft = _call_hf_model(prompt, model, os.environ.get("HF_TOKEN"))
            else:
                draft = _call_local_model(prompt, model, language)
        except Exception as exc:  # noqa: BLE001
            meta["reason"] = f"model call failed: {exc}"
            print(f"  [narration:{language}] attempt {attempt} error: {exc}", file=sys.stderr)
            return None, meta

        last_draft = draft
        ok, unsupported, total = check_numeric_grounding(draft, slim)
        over_used = []
        if ok:
            mult_ok, over_used = check_number_multiplicity(draft, slim)
            if not mult_ok:
                ok = False
                print(f"  [narration:{language}] attempt {attempt}: rejected — reused value(s) "
                      f"{over_used} more times than the source data has them (likely swapped in "
                      f"place of a different real number)", file=sys.stderr)
        # A draft with zero numbers trivially has zero *unsupported* numbers
        # — real failure caught in testing: a fine-tuned model refused the
        # task outright ("I will not assist with any data analysis...", in
        # English, for a Hindi request) and that empty non-answer passed the
        # gate because there was nothing in it to contradict the fact sheet.
        # A real grounded 3-paragraph summary of this fact sheet reliably
        # cites at least MIN_NUMBERS_EXPECTED numbers, so require a floor,
        # not just "no unsupported ones."
        if ok and total < min_numbers_expected:
            ok = False
            unsupported = []
            print(f"  [narration:{language}] attempt {attempt}: rejected — only {total} numbers "
                  f"found (expected >= {min_numbers_expected}); likely a non-answer, not a real summary",
                  file=sys.stderr)
        if ok:
            prose_ok, prose_reason = _looks_like_prose_summary(draft, min_sentences=min_sentences)
            if not prose_ok:
                ok = False
                unsupported = []
                print(f"  [narration:{language}] attempt {attempt}: rejected — {prose_reason}", file=sys.stderr)
        spelling_issues = []
        if ok:
            spelling_ok, spelling_issues = check_spelling_grammar(draft, slim, language)
            if not spelling_ok:
                ok = False
                unsupported = []
                print(f"  [narration:{language}] attempt {attempt}: rejected — spelling/grammar issues: {spelling_issues}",
                      file=sys.stderr)
        if ok:
            meta["used_model"] = True
            meta["reason"] = "passed numeric + spelling/grammar gate"
            print(f"  [narration:{language}] attempt {attempt}: passed gate", file=sys.stderr)
            return draft, meta

        last_unsupported = unsupported
        last_spelling_issues = spelling_issues
        last_over_used = over_used
        if over_used:
            print(f"  [narration:{language}] attempt {attempt}: failed gate, over-used numbers: {over_used}", file=sys.stderr)
        elif spelling_issues:
            print(f"  [narration:{language}] attempt {attempt}: failed gate, spelling/grammar: {spelling_issues}", file=sys.stderr)
        else:
            print(f"  [narration:{language}] attempt {attempt}: failed gate, unsupported numbers: {unsupported}", file=sys.stderr)
        if unsupported:
            allowed_numbers = set()
            _walk_numbers(slim, allowed_numbers)
            hints = _decimal_shift_hints(unsupported, allowed_numbers)
            hint_text = f" Specifically: {'; '.join(hints)}." if hints else ""
            prompt = (
                f"{base_prompt}\n\nYour previous draft used these numbers that do NOT appear in the "
                f"JSON: {unsupported}. Rewrite it using ONLY numbers copied exactly from the JSON above, "
                f"digit for digit including the decimal point.{hint_text}"
            )
        elif over_used:
            prompt = (
                f"{base_prompt}\n\nYour previous draft reused these numbers more times than they "
                f"actually appear in the JSON: {over_used}. You likely duplicated one value in place "
                f"of a different fact's real number. Rewrite it, making sure each distinct fact gets "
                f"its own correct value from the JSON — do not reuse one number for two different facts."
            )
        elif spelling_issues:
            prompt = (
                f"{base_prompt}\n\nYour previous draft had these spelling/grammar issues: {spelling_issues}. "
                f"Rewrite it with correct spelling and grammar, otherwise following the rules above exactly."
            )
        else:
            prompt = (
                f"{base_prompt}\n\nYour previous response did not summarize the data at all (too few "
                f"numbers were cited). Write the actual summary now, following the rules above exactly."
            )

    if last_over_used:
        meta["reason"] = f"failed number-multiplicity gate after {MAX_ATTEMPTS} attempts, over-used: {last_over_used}"
    elif last_spelling_issues:
        meta["reason"] = f"failed spelling/grammar gate after {MAX_ATTEMPTS} attempts: {last_spelling_issues}"
    else:
        meta["reason"] = f"failed numeric gate after {MAX_ATTEMPTS} attempts, unsupported: {last_unsupported}"
    # Kept for diagnosis — a rejected draft that still made it to disk is not a
    # published number, but silently discarding *why* the model failed makes
    # the failure mode impossible to debug later without spending more API
    # calls to reproduce it.
    meta["last_rejected_draft"] = last_draft
    meta["last_unsupported_numbers"] = last_unsupported
    return None, meta
