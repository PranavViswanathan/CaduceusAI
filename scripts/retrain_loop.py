"""
retrain_loop.py — LoRA fine-tuning pipeline for clinical risk assessment.

Steps:
  1. Load feedback from retrain_buffer.jsonl
  2. Check minimum batch size (MIN_RETRAIN_BATCH env var, default 5)
  3. Fetch original assessment context from PostgreSQL
  4. Build Alpaca-format training dataset
  5. Fine-tune TinyLlama-1.1B with PEFT LoRA
  6. Merge adapter and save full model to /app/models/runs/<version>/
  7. Convert merged model to GGUF via llama.cpp (if available)
  8. Register new model with Ollama via /api/create
  9. Append training run metadata to retrain_log.jsonl
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

RETRAIN_BUFFER_PATH = Path(os.getenv("RETRAIN_BUFFER_PATH", "/app/data/retrain_buffer.jsonl"))
RETRAIN_LOG_PATH = Path(os.getenv("RETRAIN_LOG_PATH", "/app/data/retrain_log.jsonl"))
MODELS_DIR = Path(os.getenv("MODELS_DIR", "/app/models"))
BASE_MODEL_NAME = os.getenv("BASE_MODEL_NAME", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
MIN_BATCH_SIZE = int(os.getenv("MIN_RETRAIN_BATCH", "5"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
FINE_TUNED_MODEL_NAME = os.getenv("FINE_TUNED_MODEL_NAME", "medical-risk-ft")
DATABASE_URL = os.getenv("DATABASE_URL", "")
LLAMA_CPP_DIR = Path(os.getenv("LLAMA_CPP_DIR", "/opt/llama.cpp"))
LORA_RANK = int(os.getenv("LORA_RANK", "8"))
LORA_ALPHA = int(os.getenv("LORA_ALPHA", "16"))
LORA_EPOCHS = int(os.getenv("LORA_EPOCHS", "2"))
LORA_LR = float(os.getenv("LORA_LR", "2e-4"))

_db_engine = None


def _get_engine():
    global _db_engine
    if _db_engine is None and DATABASE_URL:
        _db_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    return _db_engine


def load_buffer(path: Path) -> list[dict]:
    if not path.exists():
        return []
    items = []
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Line %d parse error: %s", line_num, exc)
    return items


def clear_buffer(path: Path) -> None:
    path.write_text("")


def append_log(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def fetch_assessment_context(assessment_id: str, patient_id: str) -> Optional[dict]:
    engine = _get_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            ra = conn.execute(
                text("SELECT risks, confidence, summary FROM risk_assessments WHERE id = :id"),
                {"id": assessment_id},
            ).fetchone()
            if ra is None:
                return None

            pi = conn.execute(
                text("""
                    SELECT conditions, medications, allergies, symptoms
                    FROM patient_intake
                    WHERE patient_id = :pid
                    ORDER BY submitted_at DESC
                    LIMIT 1
                """),
                {"pid": patient_id},
            ).fetchone()

            context: dict = {
                "risks": ra[0] or [],
                "confidence": ra[1] or "low",
                "summary": ra[2] or "",
                "conditions": [],
                "medications": [],
                "allergies": [],
                "symptoms": "",
            }
            if pi is not None:
                context["conditions"] = pi[0] or []
                context["medications"] = pi[1] or []
                context["allergies"] = pi[2] or []
                context["symptoms"] = pi[3] or ""
            return context
    except Exception as exc:
        logger.warning("DB fetch failed for assessment %s: %s", assessment_id, exc)
        return None


def _build_input_text(context: dict) -> str:
    conditions = ", ".join(context.get("conditions", [])) or "None"
    medications = "; ".join(
        m.get("name", str(m)) if isinstance(m, dict) else str(m)
        for m in context.get("medications", [])
    ) or "None"
    allergies = ", ".join(context.get("allergies", [])) or "None"
    symptoms = context.get("symptoms") or "None"
    return (
        f"Conditions: {conditions}\n"
        f"Medications: {medications}\n"
        f"Allergies: {allergies}\n"
        f"Symptoms: {symptoms}"
    )


def _build_corrected_output(item: dict, context: dict) -> str:
    action = item.get("action", "")
    reason = (item.get("reason") or "").strip()

    original_risks = context.get("risks", [])
    original_confidence = context.get("confidence", "low")
    original_summary = context.get("summary", "")

    if action == "override" and reason:
        corrected = {
            "risks": original_risks,
            "confidence": original_confidence,
            "summary": reason,
        }
    elif action == "flag" and reason:
        flag_note = f"{original_summary} [Clinical note: {reason}]"
        corrected = {
            "risks": original_risks,
            "confidence": original_confidence,
            "summary": flag_note,
        }
    else:
        corrected = {
            "risks": original_risks,
            "confidence": original_confidence,
            "summary": original_summary,
        }
    return json.dumps(corrected)


def build_training_example(item: dict, context: Optional[dict]) -> Optional[dict]:
    action = item.get("action", "")
    reason = (item.get("reason") or "").strip()

    if action not in ("override", "flag"):
        return None

    instruction = (
        "You are a clinical risk assessment tool. "
        "Analyze the patient data and reply with ONLY a JSON object — no prose, no markdown. "
        'Required format: {"risks":["risk1","risk2"],"confidence":"low|medium|high","summary":"one sentence"}'
    )

    if context:
        input_text = _build_input_text(context)
        output = _build_corrected_output(item, context)
    else:
        if not reason:
            return None
        input_text = "Patient data unavailable."
        output = json.dumps({"risks": [reason], "confidence": "low", "summary": reason})

    return {"instruction": instruction, "input": input_text, "output": output}


def build_dataset(items: list[dict]) -> list[dict]:
    examples = []
    for item in items:
        assessment_id = item.get("assessment_id")
        patient_id = item.get("patient_id", "")
        context = fetch_assessment_context(assessment_id, patient_id) if assessment_id else None
        example = build_training_example(item, context)
        if example:
            examples.append(example)
    logger.info("Built %d training examples from %d buffer items", len(examples), len(items))
    return examples


def _format_alpaca_prompt(example: dict) -> str:
    instruction = example["instruction"]
    inp = example["input"]
    output = example["output"]
    if inp:
        return f"### Instruction:\n{instruction}\n\n### Input:\n{inp}\n\n### Response:\n{output}"
    return f"### Instruction:\n{instruction}\n\n### Response:\n{output}"


def train_lora(examples: list[dict], run_dir: Path) -> Path:
    import torch
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    logger.info("Loading base model: %s", BASE_MODEL_NAME)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_NAME)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_NAME,
        torch_dtype=torch.float32,
        low_cpu_mem_usage=True,
    )

    lora_config = LoraConfig(
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    texts = [_format_alpaca_prompt(ex) + tokenizer.eos_token for ex in examples]
    dataset = Dataset.from_dict({"text": texts})

    def tokenize(batch):
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=512,
            padding="max_length",
        )

    tokenized = dataset.map(tokenize, batched=True, remove_columns=["text"])
    tokenized = tokenized.map(lambda x: {"labels": x["input_ids"]})

    adapter_dir = run_dir / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(run_dir / "checkpoints"),
        num_train_epochs=LORA_EPOCHS,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=LORA_LR,
        fp16=False,
        logging_steps=5,
        save_strategy="no",
        report_to="none",
        dataloader_num_workers=0,
        no_cuda=True,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )

    logger.info("Starting LoRA training on %d examples (%d epochs)...", len(examples), LORA_EPOCHS)
    trainer.train()
    logger.info("Training complete.")

    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    logger.info("Adapter saved: %s", adapter_dir)
    return adapter_dir


def merge_and_save(adapter_dir: Path, run_dir: Path) -> Path:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    merged_dir = run_dir / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Merging LoRA adapter into base model...")
    tokenizer = AutoTokenizer.from_pretrained(str(adapter_dir))
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_NAME,
        torch_dtype=torch.float32,
        low_cpu_mem_usage=True,
    )
    peft_model = PeftModel.from_pretrained(base_model, str(adapter_dir))
    merged = peft_model.merge_and_unload()
    merged.save_pretrained(str(merged_dir))
    tokenizer.save_pretrained(str(merged_dir))
    logger.info("Merged model saved: %s", merged_dir)
    return merged_dir


def convert_to_gguf(merged_dir: Path, run_dir: Path) -> Optional[Path]:
    convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
    if not convert_script.exists():
        logger.warning(
            "llama.cpp converter not found at %s — skipping GGUF conversion", convert_script
        )
        return None

    gguf_path = run_dir / "model.gguf"
    logger.info("Converting to GGUF: %s", gguf_path)
    result = subprocess.run(
        [
            sys.executable,
            str(convert_script),
            str(merged_dir),
            "--outfile", str(gguf_path),
            "--outtype", "q8_0",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        logger.error("GGUF conversion failed:\n%s", result.stderr)
        return None

    size_mb = gguf_path.stat().st_size // (1024 * 1024)
    logger.info("GGUF saved: %s (%d MB)", gguf_path, size_mb)
    return gguf_path


def register_with_ollama(gguf_path: Path, version: str) -> Optional[str]:
    versioned_name = f"{FINE_TUNED_MODEL_NAME}:{version}"
    latest_name = f"{FINE_TUNED_MODEL_NAME}:latest"
    modelfile = f"FROM {gguf_path}\n"

    try:
        with httpx.Client(timeout=300.0) as client:
            resp = client.post(
                f"{OLLAMA_URL}/api/create",
                json={"name": versioned_name, "modelfile": modelfile},
            )
            resp.raise_for_status()
            logger.info("Registered Ollama model: %s", versioned_name)

            client.post(
                f"{OLLAMA_URL}/api/copy",
                json={"source": versioned_name, "destination": latest_name},
                timeout=60.0,
            ).raise_for_status()
            logger.info("Tagged as: %s", latest_name)
        return versioned_name
    except Exception as exc:
        logger.warning("Ollama registration failed: %s", exc)
        return None


def write_model_registry(metadata: dict) -> None:
    registry_path = MODELS_DIR / "registry.json"
    registry: list = []
    if registry_path.exists():
        try:
            registry = json.loads(registry_path.read_text())
        except Exception:
            registry = []
    registry.append(metadata)
    registry_path.write_text(json.dumps(registry, indent=2))


def process_buffer() -> int:
    items = load_buffer(RETRAIN_BUFFER_PATH)

    if not items:
        logger.info("No items in retrain buffer.")
        return 0

    if len(items) < MIN_BATCH_SIZE:
        logger.info(
            "Buffer has %d item(s), below MIN_RETRAIN_BATCH=%d. Waiting for more feedback.",
            len(items),
            MIN_BATCH_SIZE,
        )
        return 0

    logger.info("Processing %d feedback items for LoRA retraining...", len(items))

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    run_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = MODELS_DIR / "runs" / run_timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    examples = build_dataset(items)
    if not examples:
        logger.warning("No valid training examples could be constructed from the buffer.")
        return 0

    action_counts: dict[str, int] = {}
    for item in items:
        a = item.get("action", "unknown")
        action_counts[a] = action_counts.get(a, 0) + 1

    metadata: dict = {
        "version": run_timestamp,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "items_used": len(items),
        "examples_built": len(examples),
        "action_breakdown": action_counts,
        "base_model": BASE_MODEL_NAME,
        "lora_rank": LORA_RANK,
        "lora_alpha": LORA_ALPHA,
        "epochs": LORA_EPOCHS,
        "status": "failed",
    }

    try:
        adapter_dir = train_lora(examples, run_dir)
        metadata["adapter_path"] = str(adapter_dir)

        merged_dir = merge_and_save(adapter_dir, run_dir)
        metadata["merged_path"] = str(merged_dir)

        gguf_path = convert_to_gguf(merged_dir, run_dir)
        metadata["gguf_path"] = str(gguf_path) if gguf_path else None

        ollama_model = None
        if gguf_path:
            ollama_model = register_with_ollama(gguf_path, run_timestamp)
        metadata["ollama_model"] = ollama_model

        metadata["status"] = "success"
        logger.info("Retraining complete. Version: %s", run_timestamp)

    except Exception as exc:
        logger.error("Retraining failed: %s", exc, exc_info=True)
        metadata["error"] = str(exc)

    append_log(RETRAIN_LOG_PATH, metadata)
    write_model_registry(metadata)

    if metadata["status"] == "success":
        clear_buffer(RETRAIN_BUFFER_PATH)
        logger.info("Buffer cleared.")
    else:
        logger.warning("Buffer NOT cleared due to training failure — items preserved for retry.")

    return len(items) if metadata["status"] == "success" else -1


if __name__ == "__main__":
    processed = process_buffer()
    sys.exit(0 if processed >= 0 else 1)
