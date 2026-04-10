"""Lightweight in-memory knowledge base used by rag_node for routine queries.

Each entry is a plain-text clinical reference paragraph.  Retrieval is done
with a simple term-frequency score so that no additional dependencies are
required.  In production this module should be swapped for a proper vector
store (pgvector, Chroma, Weaviate, etc.).
"""

_DOCUMENTS: list[str] = [
    (
        "Hypertension management: First-line agents include thiazide diuretics, "
        "ACE inhibitors (e.g. lisinopril 10–40 mg/day), ARBs (e.g. losartan 50–100 mg/day), "
        "and calcium channel blockers (e.g. amlodipine 5–10 mg/day). "
        "Lifestyle: DASH diet, sodium <2.3 g/day, aerobic exercise 150 min/week, "
        "weight loss, limit alcohol. Target BP <130/80 mmHg for most adults."
    ),
    (
        "Type 2 Diabetes management: Metformin (500–2000 mg/day) is preferred first-line. "
        "HbA1c target <7% for most patients. Add SGLT-2 inhibitor or GLP-1 agonist "
        "if cardiovascular or renal disease is present. "
        "Monitor: fasting glucose, HbA1c every 3 months, annual eye and foot exams, "
        "kidney function (eGFR, urine albumin-to-creatinine ratio)."
    ),
    (
        "Chest pain differential: Urgent causes include acute MI (STEMI/NSTEMI), "
        "unstable angina, aortic dissection, pulmonary embolism, tension pneumothorax, "
        "and cardiac tamponade. Immediate ECG, troponin, and clinical assessment required. "
        "HEART score helps risk-stratify non-ST-elevation presentations."
    ),
    (
        "Drug-drug interactions — anticoagulants: Warfarin + NSAIDs (ibuprofen, naproxen, "
        "aspirin at analgesic doses) significantly increases bleeding risk; avoid or monitor "
        "INR closely. Warfarin + ciprofloxacin/fluconazole raises INR; reduce warfarin dose "
        "and recheck INR within 3–5 days."
    ),
    (
        "Serotonin syndrome: Caused by excess serotonergic activity, most commonly from "
        "combining SSRIs/SNRIs with MAOIs, tramadol, linezolid, or triptans. "
        "Features: altered mental status, autonomic instability, neuromuscular abnormalities "
        "(clonus, hyperreflexia, hyperthermia). Discontinue offending agents immediately; "
        "cyproheptadine 12 mg can be used as adjunct."
    ),
    (
        "Metformin and contrast media: Hold metformin on the day of iodine-contrast procedures "
        "and for 48 hours afterwards in patients with eGFR <60 mL/min/1.73 m² due to risk of "
        "contrast-induced nephropathy and lactic acidosis. Restart only after renal function "
        "is confirmed stable."
    ),
    (
        "Pneumonia — community-acquired (CAP): Outpatient adults (no comorbidities): "
        "amoxicillin 1 g TID or doxycycline 100 mg BID for 5 days. "
        "Outpatient with comorbidities or recent antibiotics: respiratory fluoroquinolone "
        "(levofloxacin 750 mg/day) or beta-lactam + macrolide. "
        "CURB-65 score guides inpatient vs. outpatient decision."
    ),
    (
        "Acute kidney injury (AKI): Common causes: prerenal (dehydration, hypotension), "
        "intrinsic (ATN from contrast, aminoglycosides, NSAIDs), postrenal (obstruction). "
        "Management: identify and treat cause, maintain euvolemia, hold nephrotoxins, "
        "adjust drug doses, monitor electrolytes. "
        "Indications for dialysis: severe hyperkalemia, metabolic acidosis, pulmonary edema, "
        "uremic symptoms, or failure to respond to conservative management."
    ),
    (
        "Asthma exacerbation: Short-acting beta-agonist (salbutamol/albuterol) is the "
        "immediate reliever. Systemic corticosteroids (prednisolone 40–60 mg/day) for "
        "moderate-severe exacerbations. Magnesium sulfate 2 g IV for severe attacks. "
        "Reassess SpO2 (target ≥94%), respiratory rate, and speech. "
        "Intubation indications: GCS decline, exhaustion, silent chest, SpO2 <90% on O2."
    ),
    (
        "Sepsis (Sepsis-3): Sepsis = life-threatening organ dysfunction caused by dysregulated "
        "host response to infection (SOFA score increase ≥2). "
        "Hour-1 bundle: measure lactate, blood cultures ×2 before antibiotics, "
        "broad-spectrum antibiotics within 1 hour, 30 mL/kg crystalloid for hypotension/lactate ≥4 mmol/L, "
        "vasopressors (norepinephrine first-line) if MAP <65 mmHg despite fluids."
    ),
    (
        "Atrial fibrillation — rate vs. rhythm control: "
        "Rate control (target HR <110 bpm at rest): beta-blockers or non-dihydropyridine CCBs. "
        "Rhythm control: consider in symptomatic patients, younger patients, or first episode. "
        "Anticoagulation: CHA₂DS₂-VASc score ≥2 in men / ≥3 in women → start DOAC "
        "(apixaban, rivaroxaban, or dabigatran preferred over warfarin)."
    ),
    (
        "Opioid dosing and safety: Morphine equivalents guide conversion. "
        "Start low in opioid-naïve patients (morphine 2.5–5 mg PO q4h). "
        "Naloxone 0.4–2 mg IV/IM/IN for respiratory depression (repeat q2–3 min prn). "
        "Co-prescribe naloxone with any opioid prescription in the community. "
        "Avoid opioids + benzodiazepines combination without clear indication due to "
        "synergistic respiratory depression."
    ),
]


def retrieve(query: str, k: int = 3) -> list[str]:
    """Return the top-k knowledge-base documents most relevant to *query*.

    Relevance is scored by the number of query words that appear in each
    document (case-insensitive).  Documents with zero matches are excluded.
    This is intentionally simple — replace with a vector similarity search
    when a vector store is available.
    """
    query_tokens = set(query.lower().split())
    scored = [
        (doc, sum(1 for token in query_tokens if token in doc.lower()))
        for doc in _DOCUMENTS
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [doc for doc, score in scored[:k] if score > 0]
