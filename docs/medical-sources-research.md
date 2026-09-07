# Absorbd — Medical Document Sources & RAG Design (Research Handoff)

> Self-contained briefing for seeding Absorbd's UC/IBD knowledge library.
> Paste this whole file into a new chat to bring it up to speed.
> Generated 2026-06-05 via a multi-source, adversarially-verified deep-research pass
> (103 agents, 21 primary sources fetched, 96 claims extracted, 25 verified, 2 refuted).

---

## Research question

What are the best free and open sources of ulcerative-colitis / IBD medical documents
to seed a RAG knowledge library, covering BOTH clinician-grade content and plain-language
patient education? For each: content, bulk-access method, volume, and reuse LICENSE.
Legally-reusable open licenses strongly preferred.

## Bottom line

Build the core library from **PMC / Europe PMC commercial-use-allowed articles + DailyMed
drug labels + MedlinePlus / NIDDK patient content**. Treat **ECCO, AGA, NICE guidelines as
reference-only (permission-required)**, and **never** feed NICE content to a model.
Dominant rule across every literature source: **filter per-article by license metadata** —
never assume a blanket license.

---

## Tier 1 — Ingest freely (open license, bulk access)

### 1. PMC Open Access Subset *(top pick)*
- **Content:** 3.4M+ full-text biomedical articles/preprints; filter to UC/IBD via MeSH or full-text query.
- **Bulk access:** AWS S3 `pmc-oa-opendata` (us-east-1, anonymous — `aws s3 ... --no-sign-request`,
  no AWS account needed), plus FTP, OAI-PMH, E-utilities. Formats: JATS XML, PDF, plain text, + JSON metadata.
- **License:** CC-or-similar, partitioned into 3 buckets — Commercial Use Allowed (`oa_comm`:
  CC0, CC BY, CC BY-SA, CC BY-ND), Non-Commercial (`oa_noncomm`), Other. Each article's JSON
  has a machine-readable `license_code` field → filter programmatically.
- **Sources:** https://pmc.ncbi.nlm.nih.gov/tools/openftlist/ ,
  https://pmc.ncbi.nlm.nih.gov/tools/ftp/ , https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/
- **Catches:** (a) `oa_comm` includes **CC BY-ND** (no-derivatives) — risky for RAG chunking;
  safest derivative-friendly subset = **CC0 / CC BY / CC BY-SA only**.
  (b) Legacy FTP being deprecated (~April 2026 deprecated dir, ~Aug 2026 removal) — **build against S3**.
- **Note:** the claim "only oa_comm = CC BY + CC0 is reusable" was REFUTED (0-3); bucket is broader,
  which is exactly why you filter on actual `license_code`.

### 2. Europe PMC *(co-equal mirror)*
- **Content:** Open Access full text; same UC/IBD filtering.
- **Bulk access:** FTP — XML (weekly), PDF (monthly).
- **License:** CC-or-similar; page warns "license terms are not identical for all articles" → per-article check.
- **Source:** https://europepmc.org/downloads/openaccess

### 3. DailyMed — FDA drug labels *(cleanest reuse for the drug layer)*
- **Content:** FDA Structured Product Labeling (SPL) — covers UC meds: infliximab, adalimumab,
  vedolizumab, ustekinumab, tofacitinib, mesalamine, etc.
- **Bulk access:** Zipped SPL archives via HTTPS + FTP (`ftp://public.nlm.nih.gov/nlmdata/.dailymed/`).
- **License:** US-gov regulatory data — no copyright on label text. Among the cleanest sources.
- **Sources:** https://dailymed.nlm.nih.gov/dailymed/spl-resources-all-drug-labels.cfm ,
  https://open.fda.gov/apis/drug/label/ , https://open.fda.gov/license/

### 4. NCBI E-utilities *(targeted retrieval, not bulk)*
- 9 endpoints (ESearch/EFetch/etc.), 38 databases. Rate-limited (3 req/s, 10 with API key).
  Use for targeted UC/IBD query+fetch; use S3/FTP for whole-corpus pulls.
- **Source:** https://www.ncbi.nlm.nih.gov/books/NBK25501/

---

## Tier 2 — Use with care (preprints)

### 5. bioRxiv / medRxiv
- **Content:** Recent IBD preprints, full text PDF+XML via dedicated S3 TDM bucket.
- **Catch:** requester-pays bucket (AWS account + minimal fees — not strictly free). Per-article
  `license` ranges CC BY/CC0 → "no reuse"; filter per-article. "Broadly permissive for TDM/RAG"
  claim was REFUTED (1-2). Down-weight and flag "not peer-reviewed."
- **Source:** https://www.biorxiv.org/tdm

---

## Tier 3 — Reference-only — DO NOT ingest without permission

| Source | Why blocked |
|---|---|
| **ECCO UC guidelines** (J. Crohn's & Colitis / OUP) | "© The Author(s)... All rights reserved." Free-to-read ≠ open. A "CC BY-NC" claim was a false positive (a congress summary). Permission: journals.permissions@oup.com. https://academic.oup.com/ecco-jcc/article/16/1/2/6390052 |
| **AGA guidelines** (Gastroenterology / Elsevier) | "all rights reserved, including text/data mining, AI training." Free PMC author-manuscript = reading, not reuse. https://www.gastrojournal.org/article/S0016-5085(25)06091-3/fulltext |
| **NICE guidance** (UK) | HARD BLOCKER: "The use of NICE content to train AI models is not permitted." Free only in UK; ~£40k license outside UK; signed agreement required. https://www.nice.org.uk/reusing-our-content/nice-syndication-api |

For clinician guidance, cite/link these — never ingest their text.

---

## Patient-education sources (named in question — partially verified)

Primary government-domain sources, but not fully claim-verified — confirm before relying:
- **MedlinePlus** — US public-domain patient content; Web Service + content-use terms.
  https://medlineplus.gov/about/developers/webservices/ , https://medlineplus.gov/about/using/usingcontent/
- **NIDDK** — free web content for syndication, US-gov, IBD-specific pages.
  https://www.niddk.nih.gov/health-information/community-health-outreach/free-web-content
- **Crohn's & Colitis Foundation** — flagged scraping GRAY AREA; don't scrape patient materials
  without checking ToS/permission.

---

## Recommended system design (accuracy AND rule-following)

Core idea: separate the **retrieval corpus** (must be license-clean) from the **authority layer**
(guidelines you may only cite, not ingest). Provenance + license are first-class schema fields,
enforced at ingestion, so compliance is a property of the pipeline.

**1. License-gated ingestion (rules live here)**
- Hard filter at write time: only `license_code ∈ {CC0, CC BY, CC BY-SA}` from PMC `oa_comm` /
  Europe PMC, + DailyMed (gov) + MedlinePlus / NIDDK (public domain).
- Drop CC BY-ND from the embedding/chunking path (chunking ≈ derivative).
- Store per-chunk: `source_url`, `license_code`, `publisher`, `pub_date`, `pmid/doi`, `is_ingestible`.
  No clean license → cannot enter the vector store.
- Strip embedded figures/photos (third-party copyright even in CC0 articles).

**2. Authority layer (clinician accuracy, kept legal)**
- Index only metadata of ECCO/AGA/NICE — title, DOI, recommendation headings, public URL — never body text.
- At answer time, surface "AGA recommends X (cite + link)"; explanatory prose grounded in open corpus.
- NICE: exclude entirely from any model-touching path. Link-out only, or omit.

**3. Authority-weighted retrieval (accuracy lives here)**
- Boost by source authority: DailyMed & MedlinePlus/NIDDK > peer-reviewed reviews/meta-analyses (PMC)
  > primary studies > preprints (down-weighted, flagged).
- Recency boost (IBD therapeutics move fast).
- Hybrid retrieval (dense embeddings + BM25 keyword) for drug names / dosages / exact terms.

**4. Grounding + abstention (defensible accuracy)**
- Citation-enforced generation: every claim maps to a retrieved chunk; inline citations. No source → don't say it.
- Abstain when retrieval is weak instead of hallucinating.
- Not-medical-advice disclaimer + "consult your clinician."

**Highest-leverage single thing:** per-chunk provenance + license fields in the schema —
makes answers cite-able (accuracy) AND the corpus provably clean (compliance).

---

## Open items / next steps

1. Confirm exact bulk-access + reuse license for MedlinePlus / NIDDK / Crohn's & Colitis Foundation.
2. UMLS / MeSH license gating (free but needs signed UMLS license + UTS account) — relevant if using
   MeSH for UC/IBD topic filtering / concept normalization. Not verified this round.
3. Realistic seed volume after filtering PMC `oa_comm` → UC/IBD topic → CC0/BY/BY-SA only.
4. Possible: scaffold license-gated ingestion schema + PMC `oa_comm` UC/IBD puller (CC0/BY/BY-SA).

---

## Refuted claims (kept for honesty)

- "Only oa_comm = CC BY + CC0 is reusable; NC/ND restricted" — REFUTED 0-3 (bucket is broader; filter on license_code).
- "bioRxiv/medRxiv broadly permissive for TDM/RAG" — REFUTED 1-2 (per-article license varies, some "no reuse").
