"""
retrain_loop.py — Simulated retraining pipeline intake step.

HOW THIS WOULD WIRE INTO A REAL FINE-TUNING PIPELINE
=====================================================

1. DATA COLLECTION
   This script drains retrain_buffer.jsonl, which contains doctor feedback events
   (patient_id, action=override|flag, reason, assessment_id, timestamp). Each item
   represents a case where the model's output was challenged or flagged by a clinician.

2. DATASET CONSTRUCTION (LoRA fine-tuning format)
   For each override/flag event, reconstruct the original prompt/response pair from
   the risk_assessments table (via assessment_id). The doctor's override reason
   becomes the "preferred" completion. Format as JSONL in the Alpaca instruction format:
     {
       "instruction": "<original risk assessment prompt>",
       "input": "<patient data JSON>",
       "output": "<doctor's corrected assessment or reasoning>"
     }
   Accumulate these into a training dataset. Require a minimum batch size (e.g. 50
   examples) before triggering a training run to avoid overfitting on tiny batches.

3. LoRA FINE-TUNING
   Use Hugging Face PEFT + transformers (or llama.cpp LoRA) on the base model:
     from peft import LoraConfig, get_peft_model
     lora_config = LoraConfig(r=16, lora_alpha=32, target_modules=["q_proj","v_proj"],
                              lora_dropout=0.05, bias="none", task_type="CAUSAL_LM")
   Train for 1-3 epochs with a small learning rate (1e-4) on the curated feedback
   dataset. Use gradient checkpointing and 4-bit quantization (bitsandbytes) for
   memory efficiency on consumer GPUs.

4. EVALUATION STEP BEFORE PROMOTION
   Before promoting the new adapter to the model registry:
   a. Run a held-out evaluation set of synthetic patient cases with known ground-truth
      risk levels (established by senior clinicians).
   b. Measure: F1 on correct urgency classification, BLEU/ROUGE on narrative quality,
      false-negative rate on high-risk cases (must be ≤ baseline).
   c. Run a regression test: the new adapter must not degrade performance on the
      original benchmark by more than 2%.
   d. If evaluation passes: push adapter weights to the model registry (MLflow, W&B
      Artifacts, or a local registry) with a version tag and evaluation metrics.

5. PROMOTION TO SERVING
   The Ollama instance polls the model registry (or a deployment trigger fires via
   webhook). The new LoRA adapter is merged into the base model or loaded as a
   hot-swappable PEFT adapter. A canary rollout serves 10% of requests to the new
   adapter for 24 hours; if error rates are stable, full promotion occurs.

6. AUDIT & ROLLBACK
   Every promoted model version is linked to the exact training data batch, evaluation
   results, and the clinician feedback items that drove the update. If a post-deployment
   issue is detected, the registry supports one-click rollback to the prior version.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


RETRAIN_BUFFER_PATH = Path(__file__).parent.parent / "data" / "retrain_buffer.jsonl"
RETRAIN_LOG_PATH = Path(__file__).parent.parent / "data" / "retrain_log.jsonl"


def load_buffer(path: Path) -> list[dict]:
    if not path.exists():
        print(f"[retrain_loop] Buffer file not found: {path}")
        return []
    items = []
    with open(path, "r") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[retrain_loop] WARNING: Could not parse line {line_num}: {e}")
    return items


def clear_buffer(path: Path) -> None:
    path.write_text("")


def append_log_entry(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def print_feedback_summary(item: dict, index: int) -> None:
    patient_id = item.get("patient_id", "unknown")
    action = item.get("action", "unknown")
    reason = item.get("reason") or "(none)"
    assessment_id = item.get("assessment_id", "unknown")
    timestamp = item.get("timestamp", "unknown")

    print(f"\n  [{index + 1}] patient_id   : {patient_id}")
    print(f"       action      : {action}")
    print(f"       reason      : {reason}")
    print(f"       assessment  : {assessment_id}")
    print(f"       recorded_at : {timestamp}")


def process_buffer() -> int:
    items = load_buffer(RETRAIN_BUFFER_PATH)

    if not items:
        print("[retrain_loop] No items in retrain buffer. Nothing to process.")
        return 0

    print(f"\n[retrain_loop] Found {len(items)} item(s) in retrain buffer.")
    print("[retrain_loop] Feedback summary:")
    print("  " + "─" * 60)

    action_counts: dict[str, int] = {}
    processed_ids: list[str] = []

    for i, item in enumerate(items):
        print_feedback_summary(item, i)
        action = item.get("action", "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1
        processed_ids.append(item.get("patient_id", "unknown"))

    print("\n  " + "─" * 60)
    print(f"\n[retrain_loop] Action breakdown:")
    for action, count in action_counts.items():
        print(f"  {action:10s} : {count}")

    run_timestamp = datetime.now(timezone.utc).isoformat()

    log_entry = {
        "processed_at": run_timestamp,
        "items_processed": len(items),
        "action_breakdown": action_counts,
        "patient_ids": processed_ids,
        "status": "simulated_processed",
        "note": (
            "In production: dataset construction and LoRA fine-tuning would be "
            "triggered after minimum batch threshold is reached."
        ),
    }

    append_log_entry(RETRAIN_LOG_PATH, log_entry)
    print(f"\n[retrain_loop] Log entry written to: {RETRAIN_LOG_PATH}")

    clear_buffer(RETRAIN_BUFFER_PATH)
    print(f"[retrain_loop] Buffer cleared: {RETRAIN_BUFFER_PATH}")
    print(f"[retrain_loop] Done. {len(items)} item(s) processed at {run_timestamp}\n")

    return len(items)


if __name__ == "__main__":
    processed = process_buffer()
    sys.exit(0 if processed >= 0 else 1)
