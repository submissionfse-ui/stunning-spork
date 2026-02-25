"""
Policy Summarizer — FastAPI Backend with SSE streaming
Wraps Quacky's action-bucket + LLM analysis as a REST API.
Results stream progressively via Server-Sent Events.
"""

import asyncio
import copy
import json
import os
import subprocess
import sys
import tempfile
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional

# --- App Setup ---
app = FastAPI(title="Policy Summarizer")

# Serve static frontend files
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Path to Quacky source
QUACKY_SRC = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
_venv_python = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'venv', 'bin', 'python3'))
QUACKY_VENV_PYTHON = _venv_python if os.path.exists(_venv_python) else sys.executable

# Load .env for Anthropic key
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))


# --- Request Model ---
class AnalyzeRequest(BaseModel):
    policy: dict
    bound: int = 100
    explain: bool = True


# --- Inline helpers ---
def extract_action_buckets(policy_json):
    """Extract action buckets from Allow statements."""
    statements = policy_json.get('Statement', policy_json.get('statement', []))
    if isinstance(statements, dict):
        statements = [statements]

    buckets = []
    for i, stmt in enumerate(statements):
        effect = stmt.get('Effect', stmt.get('effect', ''))
        if effect.lower() != 'allow':
            continue

        is_not = 'NotAction' in stmt
        raw_actions = stmt.get('NotAction', stmt.get('Action', stmt.get('action', [])))
        if isinstance(raw_actions, str):
            raw_actions = [raw_actions]

        sid = stmt.get('Sid', stmt.get('sid', f'Bucket{len(buckets)+1}'))

        deny_stmts = [s for s in statements if s.get('Effect', s.get('effect', '')).lower() == 'deny']
        bucket_statements = [copy.deepcopy(stmt)] + copy.deepcopy(deny_stmts)

        bucket_policy = {
            "Version": policy_json.get("Version", "2012-10-17"),
            "Statement": bucket_statements
        }

        buckets.append({
            'sid': sid,
            'actions': raw_actions,
            'is_not': is_not,
            'policy': bucket_policy,
        })

    return buckets


def run_quacky_regex(bucket_policy, bound):
    """Run Quacky to get resource regex for a bucket.
    Returns (regex, abc_time, smt_file_path).
    Caller is responsible for cleaning up smt_file_path when done.
    """
    fd, tmp_policy = tempfile.mkstemp(suffix='.json', prefix='web_pol_')
    os.close(fd)
    tmp_output = tempfile.mktemp(prefix='web_out_')
    smt_file = tmp_output + '_1.smt2'

    try:
        with open(tmp_policy, 'w') as f:
            json.dump(bucket_policy, f)

        cmd = [
            QUACKY_VENV_PYTHON, os.path.join(QUACKY_SRC, 'quacky.py'),
            '-p1', tmp_policy,
            '-b', str(bound),
            '-o', tmp_output,
            '-s', '-pr',
        ]

        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=QUACKY_SRC)
        abc_time = time.time() - t0

        raw_regex = '∅'
        for line in proc.stdout.split('\n'):
            if 'regex_from_dfa:' in line:
                raw_regex = line.split('regex_from_dfa:')[1].strip()
                break

        return raw_regex, abc_time, smt_file
    finally:
        # Clean up the policy file, but keep the SMT file for --compare-regex
        if os.path.exists(tmp_policy):
            os.unlink(tmp_policy)


def run_compare_regex(smt_file, simplified_regex, bound):
    """Run ABC --compare-regex to compute Jaccard similarity between
    the DFA regex (from the SMT formula) and the simplified regex.
    Returns jaccard_similarity as a float (0.0-1.0), or None on failure.
    """
    fd, tmp_regex = tempfile.mkstemp(suffix='.txt', prefix='web_regex_')
    os.close(fd)

    try:
        with open(tmp_regex, 'w') as f:
            f.write(simplified_regex)

        cmd = (
            f'abc -bs {bound} -v 0 -i {smt_file} '
            f'--precise --count-tuple '
            f'--compare-regex resource {tmp_regex}'
        )

        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=120, cwd=QUACKY_SRC
        )

        # Parse Jaccard from ABC stderr (where report lines go)
        jaccard_num = None
        jaccard_den = None
        for line in proc.stderr.split('\n'):
            if 'jaccard index numerator' in line.lower():
                m = line.split(':')
                if len(m) >= 2:
                    jaccard_num = int(m[-1].strip())
            elif 'jaccard index denominator' in line.lower():
                m = line.split(':')
                if len(m) >= 2:
                    jaccard_den = int(m[-1].strip())

        if jaccard_num is not None and jaccard_den is not None and jaccard_den > 0:
            return round(jaccard_num / jaccard_den, 4)
        return None
    except Exception:
        return None
    finally:
        if os.path.exists(tmp_regex):
            os.unlink(tmp_regex)


def run_llm_simplify(raw_regex, actions_str, bucket_policy, bound):
    """Run LLM simplification + example generation via subprocess."""
    script = f"""
import json, sys, os
sys.path.insert(0, {repr(QUACKY_SRC)})
os.chdir({repr(QUACKY_SRC)})
from dotenv import load_dotenv
load_dotenv(os.path.join({repr(QUACKY_SRC)}, '..', '.env'))
from quacky import simplify_regex_with_llm

simplified, examples = simplify_regex_with_llm(
    {repr(raw_regex)}, {repr(actions_str)},
    json.loads({repr(json.dumps(bucket_policy))}), {bound}
)
print(json.dumps({{"simplified": simplified, "examples": examples}}))
"""
    proc = subprocess.run(
        [QUACKY_VENV_PYTHON, '-c', script],
        capture_output=True, text=True, timeout=300, cwd=QUACKY_SRC
    )
    if proc.returncode != 0:
        return None, []

    for line in proc.stdout.strip().split('\n'):
        line = line.strip()
        if line.startswith('{'):
            data = json.loads(line)
            return data.get('simplified'), data.get('examples', [])
    return None, []


def run_verify_path(bucket_policy, resource_path, bound):
    """Verify a single resource path via subprocess."""
    script = f"""
import json, sys, os, tempfile, argparse, copy
sys.path.insert(0, {repr(QUACKY_SRC)})
os.chdir({repr(QUACKY_SRC)})
from dotenv import load_dotenv
load_dotenv(os.path.join({repr(QUACKY_SRC)}, '..', '.env'))
from quacky import verify_resource_path

bucket_policy = json.loads({repr(json.dumps(bucket_policy))})
actions = {repr(bucket_policy['Statement'][0].get('Action', bucket_policy['Statement'][0].get('NotAction', [])))}
args = argparse.Namespace(
    bound={bound}, smt_lib=True, enc=False, constraints=False,
    policy1=None, policy2=None, output=tempfile.mktemp(),
    print_regex=False, action_buckets=False,
    query_action=None, explain=False
)
result = verify_resource_path(bucket_policy, {repr(resource_path)}, actions, args)
print("VERIFIED" if result else "FAILED")
"""
    proc = subprocess.run(
        [QUACKY_VENV_PYTHON, '-c', script],
        capture_output=True, text=True, timeout=120, cwd=QUACKY_SRC
    )
    return 'VERIFIED' in proc.stdout


def sse_event(event_type, data):
    """Format a Server-Sent Event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


# --- Routes ---
@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))


@app.post("/api/analyze")
async def analyze_policy(req: AnalyzeRequest):
    """Stream analysis results via Server-Sent Events."""
    try:
        buckets = extract_action_buckets(req.policy)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid policy: {e}")

    if not buckets:
        async def empty():
            yield sse_event("done", {"message": "No action buckets found"})
        return StreamingResponse(empty(), media_type="text/event-stream")

    async def event_stream():
        total = len(buckets)
        yield sse_event("start", {"total_buckets": total})

        for i, bucket in enumerate(buckets):
            sid = bucket['sid']
            actions = bucket['actions']
            actions_str = ', '.join(actions)

            # --- Stage 1: Run Quacky to get regex ---
            yield sse_event("stage", {
                "bucket_index": i, "stage": "abc",
                "message": f"Running ABC on bucket {i+1}/{total}..."
            })

            loop = asyncio.get_event_loop()
            raw_regex, abc_time, smt_file = await loop.run_in_executor(
                None, run_quacky_regex, bucket['policy'], req.bound
            )

            yield sse_event("bucket", {
                "bucket_index": i,
                "sid": sid,
                "actions": actions,
                "raw_regex": raw_regex,
                "abc_time": round(abc_time, 2),
                "total": total,
            })

            # --- Stage 2: LLM simplification ---
            if req.explain and raw_regex != '∅':
                yield sse_event("stage", {
                    "bucket_index": i, "stage": "llm",
                    "message": f"Simplifying regex with LLM..."
                })

                simplified, examples = await loop.run_in_executor(
                    None, run_llm_simplify, raw_regex, actions_str,
                    bucket['policy'], req.bound
                )

                yield sse_event("simplified", {
                    "bucket_index": i,
                    "simplified_regex": simplified,
                    "examples": examples,
                })

                # --- Stage 2b: Compute Jaccard similarity ---
                if simplified and smt_file and os.path.exists(smt_file):
                    yield sse_event("stage", {
                        "bucket_index": i, "stage": "jaccard",
                        "message": f"Computing Jaccard similarity..."
                    })

                    jaccard = await loop.run_in_executor(
                        None, run_compare_regex, smt_file, simplified, req.bound
                    )

                    yield sse_event("jaccard", {
                        "bucket_index": i,
                        "jaccard_similarity": jaccard,
                    })

                # --- Stage 3: Verify each path one by one ---
                if examples:
                    for j, path in enumerate(examples):
                        yield sse_event("stage", {
                            "bucket_index": i, "stage": "verify",
                            "message": f"Verifying permission set {j+1}/{len(examples)}..."
                        })

                        verified = await loop.run_in_executor(
                            None, run_verify_path, bucket['policy'], path, req.bound
                        )

                        yield sse_event("verified", {
                            "bucket_index": i,
                            "path": path,
                            "verified": verified,
                        })

            # Clean up SMT file after bucket is fully processed
            if smt_file and os.path.exists(smt_file):
                os.unlink(smt_file)

        yield sse_event("done", {"message": "Analysis complete"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# --- Run ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
