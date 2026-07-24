"""
Standalone local-model inference worker — run via the isolated venv at
C:\\venv\\mlenv (created specifically to dodge a Windows long-path pip install
failure in the main Python environment; see narration.py for why this is a
separate subprocess rather than an in-process import).

Reads a chat prompt from stdin, runs it through a small open-source
instruct model entirely on CPU, prints the generated text to stdout. No
network call, no API key, no billing — the tradeoff is quality/speed vs. the
hosted models, and real memory pressure on a machine with limited free RAM.

Usage:
    echo "some prompt" | python local_infer.py [--model Qwen/Qwen2.5-0.5B-Instruct]
"""

import argparse
import sys

try:
    # Patches ssl to validate against the OS certificate store instead of
    # Python's bundled certifi list. Needed on this network, which does TLS
    # interception via a corporate proxy whose root CA is trusted by Windows
    # but not by certifi — without this, the model download's HTTPS request
    # fails with CERTIFICATE_VERIFY_FAILED even though huggingface.co is
    # otherwise reachable fine (confirmed working via urllib elsewhere).
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--max-new-tokens", type=int, default=400)
    args = parser.parse_args()

    # sys.stdin.read() decodes using the console's active codepage on Windows
    # (often cp1252), which silently mangles piped non-ASCII text (Hindi
    # prompts) into invalid/lone-surrogate characters — those then crash the
    # Rust tokenizer deep inside apply_chat_template with an opaque
    # "TextEncodeInput must be Union[...]" TypeError that has nothing to do
    # with the model. Reading raw bytes and decoding as UTF-8 explicitly
    # matches what the caller (narration.py's subprocess.run(..., encoding=
    # "utf-8")) actually sends.
    prompt = sys.stdin.buffer.read().decode("utf-8")
    if not prompt.strip():
        print("ERROR: empty prompt on stdin", file=sys.stderr)
        sys.exit(1)

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(max(1, torch.get_num_threads()))

    print(f"Loading {args.model} ...", file=sys.stderr)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True
    )
    model.eval()

    messages = [{"role": "user", "content": prompt}]
    # Two steps rather than apply_chat_template(..., return_tensors="pt",
    # return_dict=True) in one call — that combined path throws
    # "TextEncodeInput must be Union[...]" from inside encode_batch on some
    # non-ASCII (e.g. Devanagari) prompts with this transformers version;
    # templating to plain text first and tokenizing separately avoids it.
    templated = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    inputs = tokenizer(templated, return_tensors="pt")
    input_len = inputs["input_ids"].shape[1]

    print("Generating ...", file=sys.stderr)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=True,
            temperature=0.3,
            top_p=0.9,
            pad_token_id=tokenizer.eos_token_id,
        )

    generated = output_ids[0][input_len:]
    text = tokenizer.decode(generated, skip_special_tokens=True)
    # Mirrors the stdin fix above — write UTF-8 bytes directly rather than
    # print(), which would hit the same console-codepage crash on Hindi output.
    sys.stdout.buffer.write(text.strip().encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
