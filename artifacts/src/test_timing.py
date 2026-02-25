#!/usr/bin/env python3
"""Debug: generate bucket formula and test ABC directly."""
import json, copy, time, os, sys
from frontend import sanitize_and_wrap
from backend import visit_policy_model  
from utilities import header, footer
import policy_model

# Reset globals
policy_model.static_declarations = {
    policy_model.declare('principal', 'String'),
    policy_model.declare('action', 'String'),
    policy_model.declare('resource', 'String')
}
policy_model.declarations = set()
policy_model.assertions = set()
policy_model.namespaces = set()
policy_model.actions = set()

with open('../samples/benchmark/multiple_service_access/policy.json') as f:
    pj = json.load(f)

# Bucket 1: AllowServices + all Denies
stmts = pj['Statement']
allow_s0 = stmts[0]  # AllowServices: s3:*, cloudwatch:*, ec2:*
deny_stmts = [s for s in stmts if s['Effect'] == 'Deny']

mod = copy.deepcopy(pj)
mod['Statement'] = [copy.deepcopy(allow_s0)] + copy.deepcopy(deny_stmts)

print(f"Modified policy has {len(mod['Statement'])} statements:", flush=True)
for s in mod['Statement']:
    print(f"  {s['Effect']}: {s.get('Action', s.get('NotAction', '?'))}", flush=True)

obj = sanitize_and_wrap(copy.deepcopy(mod))
domain = dict()
body = visit_policy_model(obj, domain, False, True, False, None)
formula = header() + body + footer('p0')

outfile = '/tmp/bucket1_debug.smt2'
with open(outfile, 'w') as f:
    f.write(formula)

print(f"\nFormula written to {outfile}, length: {len(formula)}", flush=True)
print(f"\n--- FORMULA ---", flush=True)
print(formula, flush=True)
print(f"--- END FORMULA ---\n", flush=True)

# Now run ABC
from utils.Shell import Shell
shell = Shell()

regex_file = '/tmp/bucket1_regex.txt'
cmd = f'abc -bs 100 -v 0 -i {outfile} --precise --count-tuple --dfa-to-re resource {regex_file} 32 126'
print(f"CMD: {cmd}", flush=True)

t0 = time.time()
out, err = shell.runcmd(cmd)
elapsed = time.time() - t0

print(f"ABC time: {elapsed:.2f}s", flush=True)
print(f"stdout: {out}", flush=True)
print(f"stderr (last 500): {err[-500:] if err else 'none'}", flush=True)

if os.path.exists(regex_file):
    with open(regex_file) as f:
        regex = f.read().strip()
    print(f"Regex: {regex}", flush=True)
else:
    print("No regex file produced", flush=True)

print("DONE", flush=True)
