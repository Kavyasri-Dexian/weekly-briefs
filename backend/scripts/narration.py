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


def _looks_like_prose_summary(draft: str):
    """Catches a second real failure mode the numeric floor alone missed: a
    model that echoes the input JSON fact sheet back verbatim (inside a
    ```json code fence) trivially passes the numeric gate at 100% — every
    number in it matches the source, because it *is* the source, not a
    summary of it. Rejects anything that looks like raw JSON rather than
    the requested flowing-paragraph prose. Also rejects drafts too short to
    be a real 3-paragraph summary (a refusal or a one-line non-answer)."""
    stripped = draft.strip()
    if "```" in draft or stripped.startswith("{") or stripped.startswith("["):
        return False, "draft looks like raw JSON/code, not prose"
    sentence_count = len(re.findall(r"[.!?।](?:\s|$)", draft))
    if sentence_count < MIN_SENTENCES:
        return False, f"only {sentence_count} sentences found (expected >= {MIN_SENTENCES})"
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
        "2. Do not include a title, date range, or heading — only the 3 paragraphs.\n"
        "3. Do NOT use bullet points, dashes, or list formatting of any kind. Write complete, "
        "grammatical sentences joined into paragraphs, e.g. 'Total arrivals rose 3% week-on-week "
        "to 457,664 tonnes.' NOT a 'Label: value' fragment like 'Week-on-week change: 3%'.\n"
        "4. Paragraph 1: total arrivals and its week-on-week change, the top traded commodity and "
        "its share, and other leading commodities. Paragraph 2: the largest price gainers and "
        "decliners, and for the top commodity, how this week's average price compares to last "
        "week, the same week last month, and the same week last year (price_trend in the JSON). "
        "Paragraph 3: market reporting compliance — how many markets reported, the top reporting "
        "market, how many reported 5-6 days and how many filed no return.\n"
        "5. Output ONLY the 3 paragraphs — no preamble, no closing remarks, no headings."
    ),
    "hi": (
        "आप एक भारतीय कृषि मंडी रिपोर्ट के लिए डेटा-से-पाठ सारांशकर्ता हैं। आपको मध्य प्रदेश की "
        "साप्ताहिक मंडी कीमतों और आवक के सत्यापित आंकड़ों वाली एक JSON फैक्ट शीट दी गई है। हिंदी में "
        "कार्यकारी नैरेटिव का मुख्य भाग ठीक 3 संक्षिप्त प्रवाहमान अनुच्छेदों में लिखें, प्रत्येक "
        "अनुच्छेद के बीच एक खाली पंक्ति छोड़ें।\n\n"
        "नियम — बिल्कुल पालन करें:\n"
        "1. केवल वही संख्याएँ उपयोग करें जो नीचे दिए गए JSON में ज्यों की त्यों मौजूद हैं। कोई गणना, "
        "अनुमान, भिन्न पूर्णांकन, या नई संख्या न बनाएं।\n"
        "2. कोई शीर्षक या दिनांक सीमा शामिल न करें — केवल 3 अनुच्छेद।\n"
        "3. बुलेट पॉइंट, डैश, या किसी भी प्रकार की सूची का उपयोग न करें। पूर्ण, व्याकरणिक वाक्यों में "
        "लिखें (कर्ता और क्रिया सहित), जैसे 'इस सप्ताह कुल आवक 3% बढ़कर 457,664 टन हो गई।' — "
        "'साप्ताहिक परिवर्तन: 3%' जैसा खंड नहीं।\n"
        "4. अनुच्छेद 1: कुल आवक और उसका साप्ताहिक परिवर्तन, सबसे अधिक कारोबार वाली वस्तु और उसकी "
        "हिस्सेदारी, तथा अन्य प्रमुख वस्तुएँ। अनुच्छेद 2: सबसे बड़ी मूल्य वृद्धि और गिरावट, और सबसे अधिक "
        "कारोबार वाली वस्तु के लिए इस सप्ताह का औसत मूल्य पिछले सप्ताह, पिछले महीने के इसी सप्ताह, और "
        "पिछले वर्ष के इसी सप्ताह की तुलना में कैसा रहा (JSON में price_trend)। अनुच्छेद 3: मंडी "
        "रिपोर्टिंग अनुपालन — कितनी मंडियों ने रिपोर्ट की, सबसे अधिक रिपोर्ट करने वाली मंडी, कितनी "
        "मंडियों ने 5-6 दिन रिपोर्ट की और कितनी ने कोई रिपोर्ट दर्ज नहीं की।\n"
        "5. केवल 3 अनुच्छेद आउटपुट करें — कोई भूमिका, शीर्षक या समापन टिप्पणी नहीं।\n\n"
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
            k: v for k, v in fs["market_compliance"].items()
            if k not in ("roster_caveat",)
        },
        "top_commodities": top_commodities,
        "price_change": {
            k: v for k, v in fs["price_change"].items()
            if k not in ("reason", "min_trading_days_for_ranking", "commodities_excluded_thin_trade")
        },
        "price_trend": price_trend,
    }


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


def _call_hf_model(prompt: str, model: str, token: str) -> str:
    from huggingface_hub import InferenceClient

    client = InferenceClient(model=model, token=token)
    completion = client.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.3,
    )
    return completion.choices[0].message.content.strip()


def _call_local_model(prompt: str, model: str, language: str) -> str:
    """Runs local_infer.py in the isolated venv as a subprocess — kept out of
    this process entirely so the main pipeline's environment never needs
    torch/transformers installed, and so a model crash/OOM can't take the
    pipeline down with it (a non-zero exit or timeout just raises here, which
    the caller treats the same as any other narration failure: fall back to
    the template). Passes the language's fine-tuned LoRA adapter if one has
    been trained and saved (see train_lora.py); otherwise runs the plain
    base model, same as before any fine-tuning existed."""
    if not os.path.exists(LOCAL_PYTHON):
        raise RuntimeError(f"local Python not found at {LOCAL_PYTHON} — see backend/scripts/local_infer.py setup")

    args = [
        LOCAL_PYTHON, os.path.join(os.path.dirname(__file__), "local_infer.py"),
        "--model", model, "--max-new-tokens", str(LOCAL_MAX_NEW_TOKENS),
    ]
    adapter_path = _lora_adapter_path(language)
    if os.path.isdir(adapter_path):
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


def narrate_with_model(fact_sheet: dict, language: str, model: str = None):
    """Attempts a grounded model draft (English or Hindi), gated against the
    fact sheet's own numbers. Returns (text_or_None, meta_dict). text is None
    if every attempt failed the gate or the model call — caller should fall
    back to the deterministic template in that case."""
    provider = NARRATION_PROVIDER
    if provider == "hf":
        token = os.environ.get("HF_TOKEN")
        model = model or DEFAULT_MODEL
        if not token:
            return None, {"model": model, "provider": provider, "attempts": 0, "used_model": False, "reason": "HF_TOKEN not set"}
    else:
        model = model or LOCAL_MODEL

    meta = {"model": model, "provider": provider, "attempts": 0, "used_model": False, "reason": None}

    slim = _slim_fact_sheet(fact_sheet)
    base_prompt = f"{PROMPT_INSTRUCTIONS[language]}\n\nJSON fact sheet:\n{json.dumps(slim, ensure_ascii=False)}"
    prompt = base_prompt
    last_unsupported = []
    last_draft = None

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
        # A draft with zero numbers trivially has zero *unsupported* numbers
        # — real failure caught in testing: a fine-tuned model refused the
        # task outright ("I will not assist with any data analysis...", in
        # English, for a Hindi request) and that empty non-answer passed the
        # gate because there was nothing in it to contradict the fact sheet.
        # A real grounded 3-paragraph summary of this fact sheet reliably
        # cites at least MIN_NUMBERS_EXPECTED numbers, so require a floor,
        # not just "no unsupported ones."
        if ok and total < MIN_NUMBERS_EXPECTED:
            ok = False
            unsupported = []
            print(f"  [narration:{language}] attempt {attempt}: rejected — only {total} numbers "
                  f"found (expected >= {MIN_NUMBERS_EXPECTED}); likely a non-answer, not a real summary",
                  file=sys.stderr)
        if ok:
            prose_ok, prose_reason = _looks_like_prose_summary(draft)
            if not prose_ok:
                ok = False
                unsupported = []
                print(f"  [narration:{language}] attempt {attempt}: rejected — {prose_reason}", file=sys.stderr)
        if ok:
            meta["used_model"] = True
            meta["reason"] = "passed numeric gate"
            print(f"  [narration:{language}] attempt {attempt}: passed gate", file=sys.stderr)
            return draft, meta

        last_unsupported = unsupported
        print(f"  [narration:{language}] attempt {attempt}: failed gate, unsupported numbers: {unsupported}", file=sys.stderr)
        if unsupported:
            prompt = (
                f"{base_prompt}\n\nYour previous draft used these numbers that do NOT appear in the "
                f"JSON: {unsupported}. Rewrite it using ONLY numbers copied exactly from the JSON above."
            )
        else:
            prompt = (
                f"{base_prompt}\n\nYour previous response did not summarize the data at all (too few "
                f"numbers were cited). Write the actual summary now, following the rules above exactly."
            )

    meta["reason"] = f"failed numeric gate after {MAX_ATTEMPTS} attempts, unsupported: {last_unsupported}"
    # Kept for diagnosis — a rejected draft that still made it to disk is not a
    # published number, but silently discarding *why* the model failed makes
    # the failure mode impossible to debug later without spending more API
    # calls to reproduce it.
    meta["last_rejected_draft"] = last_draft
    meta["last_unsupported_numbers"] = last_unsupported
    return None, meta
