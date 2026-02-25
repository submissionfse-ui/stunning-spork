#!/usr/bin/env python3
"""Quick test of imports and basic formula generation."""
import sys
print("Starting test...", flush=True)

try:
    from frontend import sanitize_and_wrap
    print("frontend OK", flush=True)
    from backend import visit_policy_model
    print("backend OK", flush=True)
    from utilities import header, footer
    print("utilities OK", flush=True)
    from expressions import expr
    print("expressions OK", flush=True)
    import policy_model
    print("policy_model OK", flush=True)
except Exception as e:
    print(f"Import error: {e}", flush=True)
    sys.exit(1)

import json

# Test with simplest policy
with open('../samples/benchmark/iam_simplest_policy/policy.json', 'r') as f:
    policy_json = json.load(f)

print(f"Policy: {policy_json}", flush=True)

# Test action bucket extraction
from action_resource_summarizer import extract_action_buckets
buckets = extract_action_buckets(policy_json)
print(f"Buckets: {buckets}", flush=True)

# Test formula generation
from action_resource_summarizer import generate_base_formula
formula, pjson = generate_base_formula(
    '../samples/benchmark/iam_simplest_policy/policy.json',
    bound=100, smt_lib=True)

print(f"Formula length: {len(formula)}", flush=True)
print("Formula (first 500 chars):", flush=True)
print(formula[:500], flush=True)

# Test constraint generation
from action_resource_summarizer import generate_action_constraint_smt
constraint = generate_action_constraint_smt(['*'], False, smt_lib=True)
print(f"Constraint: {constraint}", flush=True)

print("ALL TESTS PASSED", flush=True)
