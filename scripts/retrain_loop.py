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
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import mlflow
import mlflow.tracking
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "")
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
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "")
MLFLOW_EXPERIMENT = "medical-risk-ft"
MLFLOW_REGISTERED_MODEL = "medical-risk-ft"

_EVAL_SCENARIOS = [
    {
        "description": "diabetic with hypertension on metformin",
        "patient": {
            "conditions": ["Type 2 diabetes", "hypertension"],
            "medications": [{"name": "metformin"}, {"name": "lisinopril"}],
            "allergies": ["penicillin"],
            "symptoms": "fatigue and frequent urination",
        },
    },
    {
        "description": "warfarin + NSAID interaction",
        "patient": {
            "conditions": ["atrial fibrillation"],
            "medications": [{"name": "warfarin"}, {"name": "ibuprofen"}],
            "allergies": [],
            "symptoms": "palpitations",
        },
    },
    {
        "description": "SSRI + MAOI combination",
        "patient": {
            "conditions": ["major depressive disorder"],
            "medications": [{"name": "sertraline"}, {"name": "phenelzine"}],
            "allergies": [],
            "symptoms": "mood changes, insomnia",
        },
    },
    {
        "description": "metformin before contrast procedure",
        "patient": {
            "conditions": ["coronary artery disease", "Type 2 diabetes"],
            "medications": [{"name": "metformin"}, {"name": "aspirin"}],
            "allergies": [],
            "symptoms": "chest tightness, scheduled for CT angiogram with contrast dye",
        },
    },
    {
        "description": "healthy patient, no interactions",
        "patient": {
            "conditions": [],
            "medications": [{"name": "vitamin D"}],
            "allergies": [],
            "symptoms": "annual checkup",
        },
    },
]

_db_engine = None


# ── MLflow helpers ────────────────────────────────────────────────────────────


def _mlflow_register_and_transition(run_id: str, stage: str) -> None:
    """Register the run's model artifact and transition it to the given stage."""
    try:
        client = mlflow.tracking.MlflowClient()
        mv = mlflow.register_model(f"runs:/{run_id}/model", MLFLOW_REGISTERED_MODEL)
        client.transition_model_version_stage(
            name=MLFLOW_REGISTERED_MODEL,
            version=mv.version,
            stage=stage,
            archive_existing_versions=(stage == "Production"),
        )
        logger.info("MLflow: model v%s → %s", mv.version, stage)
    except Exception as exc:
        logger.warning("MLflow registry update failed (non-fatal): %s", exc)


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


def evaluate_candidate_model(merged_dir: Path) -> float:
    """Run the merged model against the hardcoded eval set. Returns pass rate (0.0–1.0)."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline as hf_pipeline

    logger.info("Evaluating candidate model (%d scenarios)...", len(_EVAL_SCENARIOS))
    tokenizer = AutoTokenizer.from_pretrained(str(merged_dir))
    model = AutoModelForCausalLM.from_pretrained(
        str(merged_dir), torch_dtype=torch.float32, low_cpu_mem_usage=True
    )
    pipe = hf_pipeline(
        "text-generation", model=model, tokenizer=tokenizer,
        max_new_tokens=256, do_sample=False,
    )

    passed = 0
    for scenario in _EVAL_SCENARIOS:
        patient = scenario["patient"]
        conditions = ", ".join(patient.get("conditions", [])) or "None"
        medications = "; ".join(
            m.get("name", str(m)) if isinstance(m, dict) else str(m)
            for m in patient.get("medications", [])
        ) or "None"
        allergies = ", ".join(patient.get("allergies", [])) or "None"
        symptoms = patient.get("symptoms") or "None"
        prompt = (
            "You are a clinical risk assessment tool. Reply with ONLY a JSON object — no prose, no markdown.\n"
            'Required format: {"risks":["short risk 1"],"confidence":"low","summary":"one sentence"}\n'
            "confidence must be exactly: low, medium, or high.\n\n"
            f"Conditions: {conditions}\nMedications: {medications}\n"
            f"Allergies: {allergies}\nSymptoms: {symptoms}\n\nJSON:"
        )
        try:
            full_output: str = pipe(prompt)[0]["generated_text"]
            response_part = full_output[len(prompt):] if full_output.startswith(prompt) else full_output
            json_match = re.search(r"\{.*?\}", response_part, re.DOTALL) or re.search(r"\{.*\}", response_part, re.DOTALL)
            if not json_match:
                logger.warning("Eval '%s': no JSON in response", scenario["description"])
                continue
            parsed = json.loads(json_match.group())
            if not isinstance(parsed.get("risks"), list):
                logger.warning("Eval '%s': 'risks' is not a list", scenario["description"])
                continue
            if parsed.get("confidence") not in ("low", "medium", "high"):
                logger.warning("Eval '%s': invalid confidence '%s'", scenario["description"], parsed.get("confidence"))
                continue
            if not isinstance(parsed.get("summary"), str) or not parsed["summary"].strip():
                logger.warning("Eval '%s': 'summary' missing or empty", scenario["description"])
                continue
            passed += 1
            logger.info("Eval '%s': PASS", scenario["description"])
        except Exception as exc:
            logger.warning("Eval '%s' error: %s", scenario["description"], exc)

    pass_rate = passed / len(_EVAL_SCENARIOS)
    logger.info("Eval complete: %d/%d passed (%.0f%%)", passed, len(_EVAL_SCENARIOS), pass_rate * 100)
    return pass_rate


def _set_active_model_redis(model_name: str) -> None:
    if not REDIS_URL:
        logger.warning("REDIS_URL not set — skipping active_model update")
        return
    try:
        import redis as redis_lib
        r = redis_lib.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        r.set("active_model", model_name)
        logger.info("Redis active_model set to: %s", model_name)
    except Exception as exc:
        logger.warning("Failed to update Redis active_model: %s", exc)


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

    override_rate = action_counts.get("override", 0) / len(items)

    metadata: dict = {
        "version": run_timestamp,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "items_used": len(items),
        "examples_built": len(examples),
        "action_breakdown": action_counts,
        "override_rate": round(override_rate, 4),
        "base_model": BASE_MODEL_NAME,
        "lora_rank": LORA_RANK,
        "lora_alpha": LORA_ALPHA,
        "epochs": LORA_EPOCHS,
        "status": "failed",
    }

    # Set up MLflow (non-fatal if server is unavailable)
    mlflow_run_id: Optional[str] = None
    mlflow_active = False
    if MLFLOW_TRACKING_URI:
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment(MLFLOW_EXPERIMENT)
            mlflow_active = True
        except Exception as exc:
            logger.warning("MLflow setup failed (non-fatal): %s", exc)

    mlflow_run = mlflow.start_run(run_name=run_timestamp) if mlflow_active else None

    try:
        if mlflow_run:
            try:
                mlflow.log_params({
                    "base_model": BASE_MODEL_NAME,
                    "lora_rank": LORA_RANK,
                    "lora_alpha": LORA_ALPHA,
                    "lora_epochs": LORA_EPOCHS,
                    "lora_lr": LORA_LR,
                    "items_used": len(items),
                    "examples_built": len(examples),
                    "override_rate": round(override_rate, 4),
                    "fine_tuned_model_name": FINE_TUNED_MODEL_NAME,
                })
            except Exception as exc:
                logger.warning("MLflow log_params failed (non-fatal): %s", exc)

        adapter_dir = train_lora(examples, run_dir)
        metadata["adapter_path"] = str(adapter_dir)

        merged_dir = merge_and_save(adapter_dir, run_dir)
        metadata["merged_path"] = str(merged_dir)

        eval_pass_rate = evaluate_candidate_model(merged_dir)
        metadata["eval_pass_rate"] = round(eval_pass_rate, 4)

        if mlflow_run:
            try:
                mlflow.log_metrics({
                    "eval_pass_rate": eval_pass_rate,
                    "override_rate": override_rate,
                    "items_used": len(items),
                    "examples_built": len(examples),
                })
            except Exception as exc:
                logger.warning("MLflow log_metrics failed (non-fatal): %s", exc)

        if eval_pass_rate < 1.0:
            logger.warning(
                "Eval gate failed (pass_rate=%.0f%%) — aborting promotion. Buffer preserved for retry.",
                eval_pass_rate * 100,
            )
            metadata["status"] = "eval_failed"

            if mlflow_run:
                try:
                    mlflow.set_tag("status", "eval_failed")
                    mlflow.log_artifact(str(adapter_dir), artifact_path="adapter")
                    mlflow_run_id = mlflow_run.info.run_id
                    mlflow.end_run(status="FAILED")
                    _mlflow_register_and_transition(mlflow_run_id, "Archived")
                except Exception as exc:
                    logger.warning("MLflow eval_failed logging error (non-fatal): %s", exc)

            append_log(RETRAIN_LOG_PATH, metadata)
            write_model_registry(metadata)
            return -1

        gguf_path = convert_to_gguf(merged_dir, run_dir)
        metadata["gguf_path"] = str(gguf_path) if gguf_path else None

        if mlflow_run and gguf_path:
            try:
                mlflow.log_artifact(str(gguf_path), artifact_path="model")
                mlflow.log_artifact(str(adapter_dir), artifact_path="adapter")
                mlflow.set_tags({
                    "status": "success",
                    "gguf_path": str(gguf_path),
                    "ollama_model": f"{FINE_TUNED_MODEL_NAME}:{run_timestamp}",
                })
                mlflow_run_id = mlflow_run.info.run_id
            except Exception as exc:
                logger.warning("MLflow artifact logging failed (non-fatal): %s", exc)

        ollama_model = None
        if gguf_path:
            ollama_model = register_with_ollama(gguf_path, run_timestamp)
        metadata["ollama_model"] = ollama_model

        if ollama_model:
            latest_name = f"{FINE_TUNED_MODEL_NAME}:latest"
            _set_active_model_redis(latest_name)

        metadata["status"] = "success"
        logger.info("Retraining complete. Version: %s", run_timestamp)

        if mlflow_run:
            try:
                mlflow.end_run(status="FINISHED")
                if mlflow_run_id:
                    _mlflow_register_and_transition(mlflow_run_id, "Production")
            except Exception as exc:
                logger.warning("MLflow end_run/register failed (non-fatal): %s", exc)

    except Exception as exc:
        logger.error("Retraining failed: %s", exc, exc_info=True)
        metadata["error"] = str(exc)
        if mlflow_run:
            try:
                mlflow.set_tag("status", "failed")
                mlflow.set_tag("error", str(exc))
                mlflow.end_run(status="FAILED")
            except Exception:
                pass

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
