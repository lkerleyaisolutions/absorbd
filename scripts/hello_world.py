r"""
Hello-world smoke test for Absorbd.

Proves the full base stack works end-to-end BEFORE building the 9-agent system:
  .env credentials  ->  Azure OpenAI v1 endpoint  ->  gpt-4.1-mini deployment  ->  a real completion.

Uses API-key auth (no `az login` needed). The real agent build will switch to
Entra ID auth for the Foundry IQ MCP connection, but this is the minimal proof.

Run:  venv\Scripts\python.exe scripts\hello_world.py
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Load .env from the project root (one level up from scripts/)
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]   # .../openai/v1
api_key = os.environ["AZURE_AI_PROJECT_API_KEY"]
model = os.environ["MODEL_DEPLOYMENT"]            # gpt-4.1-mini

print(f"Endpoint : {endpoint}")
print(f"Model    : {model}")
print("Calling the model...\n")

client = OpenAI(base_url=endpoint, api_key=api_key)

try:
    resp = client.responses.create(
        model=model,
        input="In one sentence, what is ulcerative colitis?",
    )
except Exception as e:
    print("FAILED to reach the model.")
    print(f"  {type(e).__name__}: {e}")
    sys.exit(1)

print("MODEL REPLIED:")
print(resp.output_text)
print("\nStack is working. Ready to build the agents.")
