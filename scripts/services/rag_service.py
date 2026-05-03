"""
RAG service: ChromaDB vector store of drug knowledge.

Used as a fallback context source when a drug is not found in the
NADAC/Orange Book warehouse. Retrieves relevant drug knowledge chunks
and injects them into the LLM prompt so the model is grounded in
real pharmacological context rather than relying on parametric memory.

The collection is seeded once at startup from DRUG_KNOWLEDGE (below)
and stored in-memory (no persistence file needed for demo).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Drug knowledge corpus ─────────────────────────────────────────────────────
# Each entry: id, drug name(s), text chunk with class/mechanism/switch context.
# Covers the demo set + common drugs likely to appear in payer claims.

DRUG_KNOWLEDGE: list[dict] = [
    {
        "id": "provigil-modafinil",
        "text": (
            "Provigil (modafinil) is a wakefulness-promoting agent used for narcolepsy, "
            "shift work sleep disorder, and obstructive sleep apnea. "
            "Generic equivalent: modafinil. FDA TE code AB. "
            "Switch rationale: modafinil is bioequivalent to Provigil; payers routinely "
            "mandate generic substitution. Typical savings: $1,000–$2,400 per fill. "
            "Clinical caution: same active ingredient, same adverse-effect profile."
        ),
    },
    {
        "id": "nuvigil-armodafinil",
        "text": (
            "Nuvigil (armodafinil) is the R-enantiomer of modafinil, used for the same "
            "sleep disorder indications as Provigil. "
            "Generic equivalent: armodafinil. FDA TE code AB. "
            "Switch rationale: generic armodafinil is therapeutically equivalent. "
            "Typical savings: $500–$1,000 per fill."
        ),
    },
    {
        "id": "abilify-aripiprazole",
        "text": (
            "Abilify (aripiprazole) is an atypical antipsychotic (dopamine partial agonist) "
            "used for schizophrenia, bipolar disorder, major depressive disorder adjunct, "
            "and irritability in autism. "
            "Generic equivalent: aripiprazole. FDA TE code AB. "
            "Switch rationale: generic aripiprazole is bioequivalent; widely mandated by payers. "
            "Typical savings: $700–$1,100 per fill. "
            "Clinical caution: monitor for akathisia, weight gain, metabolic changes during transition."
        ),
    },
    {
        "id": "lyrica-pregabalin",
        "text": (
            "Lyrica (pregabalin) is an alpha-2-delta ligand anticonvulsant used for "
            "neuropathic pain, fibromyalgia, and partial-onset seizures. "
            "Generic equivalent: pregabalin. FDA TE code AB. "
            "Switch rationale: generic pregabalin is bioequivalent. "
            "Typical savings: $400–$900 per fill. "
            "Clinical caution: taper carefully in patients with seizure history; "
            "abuse potential (Schedule V controlled substance)."
        ),
    },
    {
        "id": "zyprexa-olanzapine",
        "text": (
            "Zyprexa (olanzapine) is an atypical antipsychotic used for schizophrenia "
            "and bipolar disorder. "
            "Generic equivalent: olanzapine. FDA TE code AB. "
            "Switch rationale: generic olanzapine is bioequivalent; major cost savings opportunity. "
            "Typical savings: $800–$1,500 per fill. "
            "Clinical caution: monitor for metabolic syndrome, weight gain, and glucose dysregulation."
        ),
    },
    {
        "id": "risperdal-risperidone",
        "text": (
            "Risperdal (risperidone) is an atypical antipsychotic used for schizophrenia, "
            "bipolar disorder, and irritability in autism. "
            "Generic equivalent: risperidone. FDA TE code AB. "
            "Switch rationale: generic risperidone is bioequivalent; standard payer substitution. "
            "Typical savings: $300–$700 per fill. "
            "Clinical caution: QTc monitoring recommended; monitor for EPS."
        ),
    },
    {
        "id": "cialis-tadalafil",
        "text": (
            "Cialis (tadalafil) is a PDE5 inhibitor used for erectile dysfunction and "
            "benign prostatic hyperplasia. "
            "Generic equivalent: tadalafil. FDA TE code AB. "
            "Switch rationale: generic tadalafil is bioequivalent; same onset and duration. "
            "Typical savings: $200–$600 per fill. "
            "Clinical caution: contraindicated with nitrates; monitor blood pressure."
        ),
    },
    {
        "id": "celebrex-celecoxib",
        "text": (
            "Celebrex (celecoxib) is a selective COX-2 inhibitor NSAID used for "
            "osteoarthritis, rheumatoid arthritis, and acute pain. "
            "Generic equivalent: celecoxib. FDA TE code AB. "
            "Switch rationale: generic celecoxib is bioequivalent; substantial cost reduction. "
            "Typical savings: $150–$400 per fill. "
            "Clinical caution: cardiovascular and GI risk; use lowest effective dose."
        ),
    },
    {
        "id": "diovan-valsartan",
        "text": (
            "Diovan (valsartan) is an angiotensin II receptor blocker (ARB) used for "
            "hypertension, heart failure, and post-MI. "
            "Generic equivalent: valsartan. FDA TE code AB. "
            "Switch rationale: generic valsartan is bioequivalent. "
            "Typical savings: $100–$300 per fill. "
            "Clinical caution: monitor renal function and potassium; avoid in pregnancy."
        ),
    },
    {
        "id": "lipitor-atorvastatin",
        "text": (
            "Lipitor (atorvastatin) is an HMG-CoA reductase inhibitor (statin) used for "
            "hyperlipidemia and cardiovascular risk reduction. "
            "Generic equivalent: atorvastatin. FDA TE code AB. "
            "Switch rationale: one of the most substituted generics; very low cost. "
            "Typical savings: $50–$150 per fill. "
            "Clinical caution: monitor LFTs; myopathy risk with high-dose statin combinations."
        ),
    },
    {
        "id": "crestor-rosuvastatin",
        "text": (
            "Crestor (rosuvastatin) is a statin used for hyperlipidemia. "
            "Generic equivalent: rosuvastatin. FDA TE code AB. "
            "Switch rationale: generic rosuvastatin is widely available and bioequivalent. "
            "Typical savings: $100–$250 per fill."
        ),
    },
    {
        "id": "nexium-esomeprazole",
        "text": (
            "Nexium (esomeprazole) is a proton pump inhibitor (PPI) used for GERD, "
            "erosive esophagitis, and H. pylori eradication. "
            "Generic equivalent: esomeprazole magnesium. FDA TE code AB. "
            "Therapeutic alternatives include omeprazole, pantoprazole (cheaper generics). "
            "Switch rationale: within-class PPI switches are common payer strategy. "
            "Typical savings: $100–$300 per fill."
        ),
    },
    {
        "id": "plavix-clopidogrel",
        "text": (
            "Plavix (clopidogrel) is a P2Y12 antiplatelet agent used for ACS, MI, and "
            "stroke prevention. "
            "Generic equivalent: clopidogrel. FDA TE code AB. "
            "Switch rationale: generic clopidogrel is bioequivalent. "
            "Clinical caution: CYP2C19 poor metabolizers have reduced efficacy — "
            "genetic testing may be warranted before switch."
        ),
    },
    {
        "id": "singulair-montelukast",
        "text": (
            "Singulair (montelukast) is a leukotriene receptor antagonist used for "
            "asthma and allergic rhinitis. "
            "Generic equivalent: montelukast. FDA TE code AB. "
            "Switch rationale: generic montelukast is bioequivalent; routine payer substitution. "
            "Typical savings: $50–$150 per fill. "
            "Clinical caution: FDA black-box warning for neuropsychiatric events."
        ),
    },
    {
        "id": "ambien-zolpidem",
        "text": (
            "Ambien (zolpidem) is a non-benzodiazepine hypnotic used for insomnia. "
            "Generic equivalent: zolpidem tartrate. FDA TE code AB. "
            "Switch rationale: generic zolpidem is bioequivalent. "
            "Typical savings: $30–$80 per fill. "
            "Clinical caution: Schedule IV; risk of complex sleep behaviors; falls in elderly."
        ),
    },
    {
        "id": "synthroid-levothyroxine",
        "text": (
            "Synthroid (levothyroxine) is a thyroid hormone replacement used for hypothyroidism. "
            "Generic equivalent: levothyroxine sodium. FDA TE code AB (narrow therapeutic index). "
            "Switch rationale: generic levothyroxine is available but NTI — TSH monitoring "
            "required after any brand-to-generic or generic-to-generic switch. "
            "Clinical caution: do not switch without TSH recheck at 6–8 weeks; "
            "brand-generic substitution may require prescriber approval."
        ),
    },
    {
        "id": "lantus-insulin-glargine",
        "text": (
            "Lantus (insulin glargine U-100) is a long-acting basal insulin used for "
            "type 1 and type 2 diabetes. "
            "Biosimilar/interchangeable: Basaglar (insulin glargine), Semglee (interchangeable). "
            "Switch rationale: Semglee is FDA-designated interchangeable — can be substituted "
            "at pharmacy without prescriber intervention. "
            "Typical savings: $80–$200 per fill. "
            "Clinical caution: concentration differences (U-100 vs U-300) — verify before switch."
        ),
    },
    {
        "id": "humira-adalimumab",
        "text": (
            "Humira (adalimumab) is a TNF-alpha inhibitor biologic used for RA, psoriasis, "
            "Crohn's disease, and other inflammatory conditions. "
            "Biosimilars: Hadlima, Hyrimoz, Cyltezo (interchangeable), Yusimry. "
            "Switch rationale: interchangeable biosimilars can substitute at pharmacy. "
            "Typical savings: $500–$2,000 per fill. "
            "Clinical caution: biosimilar switches require monitoring for immunogenicity; "
            "non-medical switching is controversial for stable patients."
        ),
    },
    {
        "id": "eliquis-apixaban",
        "text": (
            "Eliquis (apixaban) is a direct oral anticoagulant (DOAC) / Factor Xa inhibitor "
            "used for DVT, PE, and AF stroke prevention. "
            "Generic status: generic apixaban became available in 2026. "
            "Switch rationale: generic apixaban expected to offer substantial savings. "
            "Clinical caution: no reversal agent difference between brand and generic; "
            "renal function monitoring required."
        ),
    },
    {
        "id": "xarelto-rivaroxaban",
        "text": (
            "Xarelto (rivaroxaban) is a Factor Xa inhibitor DOAC used for AF, DVT/PE, "
            "and ACS. "
            "Generic status: generic rivaroxaban available. FDA TE code AB. "
            "Switch rationale: generic substitution is straightforward for stable patients. "
            "Clinical caution: renal dosing adjustments required; avoid in severe hepatic impairment."
        ),
    },
    {
        "id": "spiriva-tiotropium",
        "text": (
            "Spiriva (tiotropium bromide) is a long-acting muscarinic antagonist (LAMA) "
            "inhaler used for COPD. "
            "Generic equivalent: tiotropium bromide inhalation powder. "
            "Switch rationale: generic tiotropium available; device training may be needed. "
            "Clinical caution: inhalation device differences between brand and generic may "
            "affect adherence — pharmacist counseling recommended."
        ),
    },
    {
        "id": "advair-fluticasone-salmeterol",
        "text": (
            "Advair Diskus (fluticasone propionate / salmeterol) is an ICS/LABA combination "
            "inhaler used for asthma and COPD. "
            "Generic equivalent: fluticasone propionate / salmeterol inhalation powder. "
            "Switch rationale: FDA-approved generic available (Wixela Inhub). "
            "Typical savings: $100–$300 per fill. "
            "Clinical caution: inhaler technique training required; do not switch mid-exacerbation."
        ),
    },
    {
        "id": "celexa-citalopram",
        "text": (
            "Celexa (citalopram) is an SSRI antidepressant. "
            "Generic equivalent: citalopram hydrobromide. FDA TE code AB. "
            "Switch rationale: generic citalopram is bioequivalent; routine payer substitution. "
            "Typical savings: $20–$60 per fill. "
            "Clinical caution: QTc prolongation at high doses; dose cap at 40mg."
        ),
    },
    {
        "id": "zoloft-sertraline",
        "text": (
            "Zoloft (sertraline) is an SSRI antidepressant used for depression, OCD, PTSD, "
            "panic disorder, and social anxiety. "
            "Generic equivalent: sertraline hydrochloride. FDA TE code AB. "
            "Switch rationale: one of the most commonly dispensed generics. Very low cost. "
            "Typical savings: $10–$40 per fill."
        ),
    },
    {
        "id": "wellbutrin-bupropion",
        "text": (
            "Wellbutrin (bupropion) is an NDRI antidepressant also used for smoking cessation. "
            "Generic equivalent: bupropion hydrochloride. FDA TE code AB. "
            "Switch rationale: generic bupropion is bioequivalent. "
            "Clinical caution: seizure risk at high doses; do not use in eating disorder patients."
        ),
    },
    {
        "id": "concerta-methylphenidate",
        "text": (
            "Concerta (methylphenidate HCl extended-release) is a CNS stimulant used for ADHD. "
            "Generic equivalents: methylphenidate ER (OROS formulation). "
            "Switch rationale: only generics with OROS delivery rated AB; others rated BX. "
            "Clinical caution: verify TE code is AB before substituting; BX generics may have "
            "different release profiles. Schedule II — transfer restrictions apply."
        ),
    },
    {
        "id": "adderall-amphetamine",
        "text": (
            "Adderall (mixed amphetamine salts) is used for ADHD and narcolepsy. "
            "Generic equivalent: amphetamine salts (mixed). FDA TE code AB. "
            "Switch rationale: generic amphetamine salts are bioequivalent. "
            "Clinical caution: Schedule II controlled substance; supply shortages may affect "
            "generic availability — check formulary."
        ),
    },
    {
        "id": "neurontin-gabapentin",
        "text": (
            "Neurontin (gabapentin) is an anticonvulsant used for partial seizures and "
            "postherpetic neuralgia. Also used off-label for neuropathic pain. "
            "Generic equivalent: gabapentin. FDA TE code AB. "
            "Switch rationale: generic gabapentin is inexpensive and bioequivalent. "
            "Typical savings: $20–$80 per fill. "
            "Clinical caution: Schedule V in some states; monitor for abuse potential."
        ),
    },
    {
        "id": "topamax-topiramate",
        "text": (
            "Topamax (topiramate) is an anticonvulsant used for epilepsy and migraine prevention. "
            "Generic equivalent: topiramate. FDA TE code AB. "
            "Switch rationale: generic topiramate is bioequivalent. "
            "Clinical caution: cognitive side effects ('Dopamax'); kidney stone risk; "
            "teratogenic — verify contraception for women of childbearing age."
        ),
    },
    {
        "id": "paxil-paroxetine",
        "text": (
            "Paxil (paroxetine) is an SSRI with additional anticholinergic properties, "
            "used for depression, OCD, panic, PTSD, and social anxiety. "
            "Generic equivalent: paroxetine hydrochloride. FDA TE code AB. "
            "Switch rationale: generic paroxetine is bioequivalent. "
            "Clinical caution: highest discontinuation syndrome risk of all SSRIs — "
            "taper slowly; do not abrupt-switch."
        ),
    },
    {
        "id": "general-generic-switch",
        "text": (
            "Generic drug substitution is the practice of dispensing a generic drug instead of "
            "a brand-name drug. FDA requires generic drugs to have the same active ingredient, "
            "strength, dosage form, and route of administration as the brand. "
            "TE code AB means the FDA has determined the generic is therapeutically equivalent "
            "and can be substituted without prescriber intervention in most states. "
            "TE code BX or blank means equivalence is uncertain and prescriber approval is needed. "
            "Payers use NADAC (National Average Drug Acquisition Cost) as a benchmark for "
            "pricing generic vs brand drugs. Gross savings = (brand unit cost - generic unit cost) "
            "multiplied by quantity dispensed."
        ),
    },
]

# ── ChromaDB collection (lazy-initialized) ────────────────────────────────────
_collection = None


def _get_collection():
    """Initialize ChromaDB in-memory collection and seed it on first call."""
    global _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
        from chromadb.utils import embedding_functions

        client = chromadb.Client()  # ephemeral in-memory

        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

        _collection = client.get_or_create_collection(
            name="drug_knowledge",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

        if _collection.count() == 0:
            _collection.add(
                ids=[d["id"] for d in DRUG_KNOWLEDGE],
                documents=[d["text"] for d in DRUG_KNOWLEDGE],
            )
            logger.info("RAG: seeded ChromaDB with %d drug knowledge chunks.", len(DRUG_KNOWLEDGE))

    except Exception as exc:
        logger.warning("RAG: ChromaDB init failed — %s. RAG context will be skipped.", exc)
        _collection = None

    return _collection


def retrieve_drug_context(drug_name: str, n_results: int = 3) -> str:
    """
    Embed drug_name and retrieve the top-n most relevant knowledge chunks.
    Returns a single string suitable for injection into an LLM prompt.
    Returns empty string if ChromaDB is unavailable.
    """
    col = _get_collection()
    if col is None:
        return ""

    try:
        results = col.query(
            query_texts=[drug_name],
            n_results=min(n_results, col.count()),
        )
        docs = results.get("documents", [[]])[0]
        if not docs:
            return ""
        context = "\n\n".join(f"- {d}" for d in docs)
        logger.debug("RAG: retrieved %d chunks for '%s'", len(docs), drug_name)
        return context
    except Exception as exc:
        logger.warning("RAG: retrieval failed for '%s' — %s", drug_name, exc)
        return ""
