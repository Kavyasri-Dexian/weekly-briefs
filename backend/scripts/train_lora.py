"""
Fine-tunes the local narration model (Qwen2.5-0.5B-Instruct) via LoRA on the
training pairs from build_training_data.py — self-distillation from the
deterministic template, so the model learns to reliably produce grounded,
gate-passing prose instead of drifting into unsupported numbers (its main
failure mode observed in production this session).

Runs in the isolated venv (C:\\venv\\mlenv) via local_infer.py's sibling
scripts — same reasoning as local_infer.py: keep torch/transformers/peft out
of the main pipeline environment entirely.

Saves a LoRA adapter (a few MB, not a full model copy) to --output-dir.
narration.py's local provider loads this adapter automatically if present
at the default path (see LOCAL_LORA_ADAPTER in narration.py) — no
reconfiguration needed after training completes.

Usage:
    python train_lora.py --lang en --output-dir ../lora_adapter_en
    python train_lora.py --lang hi --output-dir ../lora_adapter_hi
"""

import argparse
import json
import os
import sys

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def load_examples(path):
    examples = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True, choices=["en", "hi"])
    parser.add_argument("--training-data", default=None, help="defaults to training_data_<lang>.jsonl")
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct")
    parser.add_argument("--output-dir", default=None, help="defaults to ../lora_adapter_<lang>")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    args = parser.parse_args()

    data_path = args.training_data or os.path.join(os.path.dirname(__file__), f"training_data_{args.lang}.jsonl")
    output_dir = args.output_dir or os.path.join(os.path.dirname(__file__), "..", f"lora_adapter_{args.lang}")

    examples = load_examples(data_path)
    print(f"Loaded {len(examples)} training examples from {data_path}", file=sys.stderr)
    if len(examples) < 5:
        print("Too few examples to fine-tune meaningfully — aborting.", file=sys.stderr)
        sys.exit(1)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, DataCollatorForLanguageModeling, Trainer, TrainingArguments

    print(f"Loading base model {args.model} ...", file=sys.stderr)
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.float32, low_cpu_mem_usage=True)

    lora_config = LoraConfig(
        r=8, lora_alpha=16, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "v_proj"],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Gradient checkpointing trades recomputation (slower) for not holding
    # every layer's activations in memory at once (much lower peak RAM) — a
    # real fix for training on this machine: the first attempt at ~2700
    # tokens/example pushed system memory to 98% load without this enabled.
    model.config.use_cache = False  # incompatible with gradient checkpointing
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()  # required for PEFT + checkpointing together

    def to_text(example):
        messages = [
            {"role": "user", "content": example["prompt"]},
            {"role": "assistant", "content": example["completion"]},
        ]
        return tokenizer.apply_chat_template(messages, tokenize=False)

    def tokenize(example):
        text = to_text(example)
        # No fixed-length padding here — with per_device_train_batch_size=1,
        # the collator below pads each micro-batch to its own single
        # example's length, so there's no wasted compute on padding tokens.
        # (A real bug caught before this: max_length=1536 with our actual
        # ~2700-token examples was silently truncating every example, most
        # likely cutting off the assistant completion entirely — the model
        # would have trained on almost no real supervision signal.)
        enc = tokenizer(text, truncation=True, max_length=3072)
        enc["labels"] = list(enc["input_ids"])
        return enc

    dataset = Dataset.from_list(examples).map(tokenize, remove_columns=["prompt", "completion"])
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    training_args = TrainingArguments(
        output_dir=os.path.join(output_dir, "_checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=args.lr,
        logging_steps=1,
        save_strategy="no",
        report_to=[],
        use_cpu=True,
    )

    trainer = Trainer(model=model, args=training_args, train_dataset=dataset, data_collator=collator)
    print("Starting training ...", file=sys.stderr)
    trainer.train()

    os.makedirs(output_dir, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"Saved LoRA adapter to {output_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
