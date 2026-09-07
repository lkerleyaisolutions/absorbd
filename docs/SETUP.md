# Setup: build the full Absorbd system on your own Azure

This guide stands up the complete reasoning system, **including the Foundry IQ
knowledge base**, on your own Azure account. Nothing here touches the original
author's resources.

The knowledge base content is **not stored as a database in this repo**. Instead, the
public-domain source documents (NIH ODS nutrient fact sheets, FDA DailyMed drug labels)
ship under [`data/raw/`](../data/raw), and the build scripts chunk, embed, and upload
them into *your* Azure AI Search. Because the sources are committed, the rebuild runs
**offline and deterministic**, no live scraping required.

> **Just want to click around?** You do not need any of this to explore the doctor and
> patient app, journal, trends, lab tables, and correlation engine. Those run on local
> SQLite with no Azure. See the "Try it yourself" section of the [README](../README.md).
> This guide is only for the live 9-agent reasoning.

---

## What you will create

| Resource | Purpose |
|----------|---------|
| Azure AI Foundry project (or Azure OpenAI resource) | Hosts the model + embedding deployments |
| `gpt-4.1-mini` deployment | Agent reasoning + knowledge-base query planning |
| `text-embedding-3-small` deployment | Embeds documents and queries (1536 dims) |
| Azure AI Search (Standard tier, semantic ranker enabled) | The vector index + Foundry IQ knowledge base |

**Roughly ~30 minutes**, most of it waiting on resource provisioning.

---

## Prerequisites

- An Azure subscription with quota for `gpt-4.1-mini` and `text-embedding-3-small`.
  Quota is region-specific; pick a region that has both (the author used **East US 2**).
- Python 3.13 and Node.js 18+.
- This repo cloned, with the Python environment installed (see the [README](../README.md)).

---

## Step 1: Provision the Azure resources

### 1a. Azure AI Foundry project + model deployments

1. In the [Azure AI Foundry portal](https://ai.azure.com), create (or open) a project.
2. Under **Models + endpoints → Deploy model**, deploy:
   - **`gpt-4.1-mini`** (give the deployment the name `gpt-4.1-mini`)
   - **`text-embedding-3-small`** (give the deployment the name `text-embedding-3-small`)

   The deployment **names** must match the `MODEL_DEPLOYMENT` and `EMBEDDING_DEPLOYMENT`
   values in your `.env`, or the scripts will 404.
3. From the project **Overview** and **Keys** pages, collect the endpoint and API key
   (used below).

### 1b. Azure AI Search

1. In the [Azure portal](https://portal.azure.com), create an **Azure AI Search**
   service on the **Standard (S1)** tier.
2. Enable the **semantic ranker** (Settings → Semantic ranker → Free or Standard). The
   index uses a semantic configuration, so this must be on.
3. From the service **Overview**, copy the URL; from **Settings → Keys**, copy a key.

---

## Step 2: Fill in `.env`

Copy the template and fill in the values you just collected:

```bash
cp .env.example .env        # Windows: Copy-Item .env.example .env
```

| Variable | Where it comes from | Notes |
|----------|--------------------|-------|
| `AZURE_OPENAI_ENDPOINT` | Foundry project | Must end in `/openai/v1` |
| `AZURE_AI_PROJECT_API_KEY` | Foundry project → Keys | |
| `MODEL_DEPLOYMENT` | your `gpt-4.1-mini` deployment name | default `gpt-4.1-mini` |
| `EMBEDDING_DEPLOYMENT` | your `text-embedding-3-small` deployment name | default `text-embedding-3-small` |
| `AZURE_SEARCH_ENDPOINT` | Search service Overview | `https://<name>.search.windows.net` |
| `AZURE_SEARCH_KEY` | Search service → Keys | admin key for the build; see security note below |
| `KNOWLEDGE_BASE_NAME` | leave as `absorb-iq-kb` | |

The remaining keys (`PROJECT_RESOURCE_ID`, `PROJECT_CONNECTION_NAME`,
`FOUNDRY_IQ_MCP_TOOL`, `AZURE_CONTENT_SAFETY_*`) are **not required** for the
local-retrieval path used here. Leave them blank.

---

## Step 3: Build the knowledge base

With the Python environment active, run the build scripts in order:

```powershell
python scripts\create_index.py            # create the Azure AI Search index (vector + semantic + vectorizer)
python scripts\ingest_ods.py              # NIH ODS nutrient fact sheets (reads the committed snapshot)
python scripts\ingest_dailymed.py         # FDA DailyMed IBD drug labels (reads the committed snapshot)
python scripts\create_knowledge_base.py   # wire the knowledge source + knowledge base
```

Because `data/raw/ods/` and `data/raw/dailymed/` are committed, the ingest scripts read
from those files instead of fetching from the internet. This reproduces the core
knowledge base (~699 chunks).

**Optional extra sources** (these *do* fetch from the network and are not required):

```powershell
python scripts\ingest_studies.py          # adversarially-verified IBD correlation studies (committed JSON)
python scripts\ingest_pmc.py              # PMC open-access articles (re-fetched; not in the snapshot)
```

---

## Step 4: Verify retrieval

```powershell
python scripts\test_knowledge_base.py
```

This runs a real clinical query through the Foundry IQ knowledge base (the same agentic
path the agents use) and prints grounded, cited references. If you get references back,
the IQ layer is live.

---

## Step 5: Seed demo data and run

Follow the "Try it yourself" section of the [README](../README.md): seed the demo
doctor and patients, start the backend and frontend, and log in. With the knowledge base
built, the **Analyze** button now runs the full live 9-agent reasoning against your
knowledge base.

---

## Extending the knowledge base

The knowledge base is designed to grow, and adding more relevant clinical evidence is the
most direct way to improve Absorbd's reasoning. Richer sources mean stronger retrieval and
better citations on every agent's findings.

**High-value sources to add next:**

- **ECCO 2025** IBD consensus guidelines
- **ACG 2024** Ulcerative Colitis clinical guideline
- More **NIH ODS** nutrient fact sheets (the committed snapshot covers 13)
- **Crohn's & Colitis Foundation** nutrition guidance
- A custom **drug-nutrient interaction** dataset for additional medications

**How to add a source.** The pipeline is source-agnostic, so you only write a parser; the
chunk, embed, upload, and retrieval steps are reused as-is.

1. Turn your source into `IngestDoc` records ([`scripts/ingestion.py`](../scripts/ingestion.py)):

   ```python
   IngestDoc(
       content=...,        # the text to index
       title=...,
       source=...,         # e.g. "ECCO 2025"
       source_url=...,     # citation link shown in the UI
       doc_type=...,       # e.g. "guideline"
       nutrient="",        # optional
       evidence_level="",  # optional, e.g. "A"
       key_parts=(...),    # stable id parts so re-runs upsert instead of duplicating
   )
   ```

2. Hand the list to `ingest(docs)` from `ingestion.py` (it chunks, embeds, and uploads).
   Mirror an existing orchestrator such as
   [`scripts/ingest_dailymed.py`](../scripts/ingest_dailymed.py).

3. Re-run `python scripts\create_knowledge_base.py` so the knowledge base picks up the new
   content. No index or schema changes are needed.

> **Licensing:** if you also want to commit a source snapshot (as this repo does for the
> public-domain NIH ODS and FDA DailyMed documents), only commit content you have the right
> to redistribute. Keep mixed-license material (e.g. PMC articles) out of the repo.

---

## Cost notes

- **Azure AI Search (Standard tier)** bills hourly while it exists (roughly a few dollars
  per day), independent of how much you query it. **Delete or pause the service when you
  are done** to stop the charge.
- **`gpt-4.1-mini`** and **`text-embedding-3-small`** bill per token. A full knowledge-base
  build is a one-time embedding cost of a few cents; each analysis is on the order of a
  dime. Both are inexpensive.

## Security note

The build and the agents currently authenticate to Azure AI Search with the **admin
key**. For a shared or public deployment, switch the agent retrieval path to a read-only
**query key** (the admin key is only needed for the build scripts). This is flagged in
[`agents/_base.py`](../agents/_base.py).
