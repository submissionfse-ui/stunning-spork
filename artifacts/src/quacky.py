from frontend import validate_args
# from tabulate import tabulate
from translator import call_translator
from utilities import *
from utils.Shell import Shell

import argparse as ap
import copy
import json
import math
import os
import re as re_mod
import subprocess
import sys
import tempfile
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

def call_abc(args):
    shell = Shell()
    policy1, policy2 = validate_args(args)

    # Call ABC on formula 1
    cmd = 'abc -bs {} -v 0 -i {}_1.smt2 --precise --count-tuple'.format(args.bound, args.output)
    if args.variable:
        cmd += ' --count-variable principal,action,resource'

    if args.models and int(args.models) > 0:
        filename = os.path.abspath(os.getcwd())+"/P1_not_P2.models"
        with open(filename,"w") as f:
            pass
        cmd += ' --get-num-random-models {} {} {} resource {}'.format(args.models, args.minrange, args.maxrange, filename)
    
    if args.printregex:
        cmd += ' --print-regex resource'

    out, err = shell.runcmd(cmd)
    if args.verbose:
        print(out, err)

    result1 = get_abc_result_line(out, err)

    print('Policy 1 ⇏ Policy 2' if policy2 else 'Policy 1')

    # Format results table
    # table1 = [
    #     ['Solve Time (ms)', result1['solve_time']],
    #     ['satisfiability', result1['is_sat']]
    # ]

    print("Solve Time (ms): " + result1.get('solve_time', 'N/A'))
    print("satisfiability: " + result1.get('is_sat', 'N/A'))

    if 'count' in result1 and int(result1['count']) > 0:
        print("Count Time (ms): " + result1['count_time'])
        print("lg(requests): " + str(math.log2(int(result1['count']))))
        # table1 += [
        #     ['Count Time (ms)', result1['count_time']],
        #     ['lg(requests)', math.log2(int(result1['count']))]
        # ]
    else:
        print("requests: 0")
        # table1.append(['requests', 0])

    # for k, v in result1['var'].items():
    #     if int(v['count']) > 0:
    #         table1.append(['lg({})'.format(k), math.log2(int(v['count']))])
    #     else:
    #         table1.append([k, 0])
    
    
    # print(tabulate(table1, tablefmt = 'fancy_grid'))
    print()

    if args.printregex and 'count' in result1:
        print("regex_from_dfa: {}".format(result1['regex_from_dfa']))

    # if given regex for resource, compare against resources from policy comparison
    if args.compareregex:
        cmd = 'abc -bs {} -v 0 -i {}_1.smt2 --precise --count-tuple'.format(args.bound, args.output)
        cmd += ' --compare-regex {} {}'.format('resource', args.compareregex)
        # print(cmd)
        out, err = shell.runcmd(cmd)
        if args.verbose:
            print(out, err)

        result = get_abc_result_line(out, err)
        is_valid = ('is_sat' in result and result['is_sat'] == 'sat')
        print(result)
        if is_valid and "baseline_regex" not in result:
            error = ""
            error += "FATAL ERROR FROM ABC" + '\n'
            error += "------output from ABC:-----" + '\n'
            error += out + '\n'
            error += "------error from ABC:-----" + '\n'
            error += err + '\n'
            error += "------output_1.smt2:-----" + '\n'
            with open("{}_1.smt2".format(args.output),'r') as f:
                error += f.read() + '\n'
            error += "------output_2.smt2:-----" + '\n'
            with open("{}_2.smt2".format(args.output),'r') as f:
                error += f.read() + '\n'
            error += "------regex from input-----" + '\n'
            with open(args.compareregex, 'r') as f:
                error += f.read() + '\n'
            error += "------policy1----" + '\n'
            with open(args.policy1, 'r') as f:
                error += f.read() + '\n'
            error += "-----policy2----" + '\n'
            if args.policy2:
                with open(args.policy2, 'r') as f:
                    error += f.read() + '\n'
            error += "FATAL END"
            
            raise Exception(error)

        print("-----------------------------------------------------------")
        print("Baseline Regex Count          : " + (result["baseline_regex"] if is_valid else '0'))
        print("Synthesized Regex Count       : " + (result["synthesized_regex"] if is_valid else '0'))
        print("Baseline_Not_Synthesized Count: " + (result["baseline_not_synthesized"] if is_valid else '0'))
        print("Not_Baseline_Synthesized_Count: " + (result["not_baseline_synthesized"] if is_valid else '0'))
        print("regex_from_dfa                : " + (result["regex_from_dfa"] if is_valid else '0'))
        print("regex_from_llm                : " + (result["regex_from_llm"] if is_valid else '0'))
        print("ops_regex_from_dfa            : " + (result["ops_regex_from_dfa"] if is_valid else '0'))
        print("ops_regex_from_llm            : " + (result["ops_regex_from_llm"] if is_valid else '0'))
        print("length_regex_from_dfa         : " + (result["length_regex_from_dfa"] if is_valid else '0'))
        print("length_regex_from_llm         : " + (result["length_regex_from_llm"] if is_valid else '0'))
        print("jaccard_numerator             : " + (result["jaccard_numerator"] if is_valid else '0'))
        print("jaccard_denominator           : " + (result["jaccard_denominator"] if is_valid else '0'))
        print("similarity1                   : " + (str(round(int(result["jaccard_numerator"]) / int(result["jaccard_denominator"]),2)) if is_valid else '0'))
        
        
    if not policy2:
        return

    # Call ABC on formula 2
    cmd = 'abc -bs {} -v 0 -i {}_2.smt2 --precise --count-tuple'.format(args.bound, args.output)
    if args.variable:
        cmd += ' --count-variable principal,action,resource'
        
    if args.models and int(args.models) > 0:
        filename = os.path.abspath(os.getcwd())+"/not_P1_P2.models"
        with open(filename,"w") as f:
            pass
        cmd += ' --get-num-random-models {} {} {} resource {}'.format(args.models, args.minrange, args.maxrange, filename)
    
    out, err = shell.runcmd(cmd)
    if args.verbose:
        print(out, err)

    result2 = get_abc_result_line(out, err)

    print('Policy 2 ⇏ Policy 1')
    print("Solve Time (ms): " + result2.get('solve_time', 'N/A'))
    print("satisfiability: " + result2.get('is_sat', 'N/A'))

    # Format results table
    # table2 = [
    #     ['Solve Time (ms)', result2['solve_time']],
    #     ['satisfiability', result2['is_sat']]
    # ]

    if 'count' in result2 and int(result2['count']) > 0:
        print("Count Time (ms): " + result2['count_time'])
        print("lg(requests): " + str(math.log2(int(result2['count']))))
        # table2 += [
        #     ['Count Time (ms)', result2['count_time']], 
        #     ['lg(requests)', math.log2(int(result2['count']))]
        # ]
    else:
        print("requests: 0")
        # table2.append(['requests', 0])

    # for k, v in result2['var'].items():
    #     if int(v['count']) > 0:
    #         table2.append(['lg({})'.format(k), math.log2(int(v['count']))])
    #     else:
    #         table2.append([k, 0])
    
    # print('Policy 2 ⇏ Policy 1')
    # print(tabulate(table2, tablefmt = 'fancy_grid'))
    print()

    # if given regex for resource, compare against resources from policy comparison
    if args.compareregex:
        cmd = 'abc -bs {} -v 0 -i {}_2.smt2 --precise --count-tuple'.format(args.bound, args.output)
        cmd += ' --compare-regex {} {}'.format('resource', args.compareregex2)
        out, err = shell.runcmd(cmd)
        if args.verbose:
            print(out, err)

        result = get_abc_result_line(out, err)
        is_valid = ('is_sat' in result and result['is_sat'] == 'sat')
        if is_valid and "baseline_regex" not in result:
            error = ""
            error += "FATAL ERROR FROM ABC" + '\n'
            error += "------output from ABC:-----" + '\n'
            error += out + '\n'
            error += "------error from ABC:-----" + '\n'
            error += err + '\n'
            error += "------output_1.smt2:-----" + '\n'
            with open("{}_1.smt2".format(args.output),'r') as f:
                error += f.read() + '\n'
            error += "------output_2.smt2:-----" + '\n'
            with open("{}_2.smt2".format(args.output),'r') as f:
                error += f.read() + '\n'
            error += "------regex2 from input-----" + '\n'
            with open(args.compareregex2, 'r') as f:
                error += f.read() + '\n'
            error += "------policy1----" + '\n'
            with open(args.policy1, 'r') as f:
                error += f.read() + '\n'
            error += "-----policy2----" + '\n'
            if args.policy2:
                with open(args.policy2, 'r') as f:
                    error += f.read() + '\n'
            error += "FATAL END"
            
            raise Exception(error)

        print("-----------------------------------------------------------")
        print("Baseline Regex Count          : " + (result["baseline_regex"] if is_valid else '0'))
        print("Synthesized Regex Count       : " + (result["synthesized_regex"] if is_valid else '0'))
        print("Baseline_Not_Synthesized Count: " + (result["baseline_not_synthesized"] if is_valid else '0'))
        print("Not_Baseline_Synthesized_Count: " + (result["not_baseline_synthesized"] if is_valid else '0'))
        print("regex_from_dfa                : " + (result["regex_from_dfa"] if is_valid else '0'))
        print("regex_from_llm                : " + (result["regex_from_llm"] if is_valid else '0'))
        print("ops_regex_from_dfa            : " + (result["ops_regex_from_dfa"] if is_valid else '0'))
        print("ops_regex_from_llm            : " + (result["ops_regex_from_llm"] if is_valid else '0'))
        print("length_regex_from_dfa         : " + (result["length_regex_from_dfa"] if is_valid else '0'))
        print("length_regex_from_llm         : " + (result["length_regex_from_llm"] if is_valid else '0'))
        print("jaccard_numerator             : " + (result["jaccard_numerator"] if is_valid else '0'))
        print("jaccard_denominator           : " + (result["jaccard_denominator"] if is_valid else '0'))
        print("similarity2                   : " + (str(round(int(result["jaccard_numerator"]) / int(result["jaccard_denominator"]),2)) if is_valid else '0'))
        print()



    if result1['is_sat'] == 'sat' and result2['is_sat'] == 'sat':
        print('Policy 1 and Policy 2 do not subsume each other.')
    elif result1['is_sat'] == 'sat' and result2['is_sat'] == 'unsat':
        print('Policy 1 is more permissive than Policy 2.')
    elif result1['is_sat'] == 'unsat' and result2['is_sat'] == 'sat':
        print('Policy 1 is less permissive than Policy 2.')
    else:
        print('Policy 1 and Policy 2 are equivalent.')

def extract_action_buckets(policy_json):
    """
    Extract action buckets from Allow statements.
    Each bucket = one Allow statement's actions + a modified policy
    containing just that Allow + all Deny statements.

    Returns:
        list of dicts: [{'actions': [...], 'is_not': bool, 'sid': str, 'policy': {...}}, ...]
    """
    stmts = policy_json.get('Statement', [])
    deny_stmts = [s for s in stmts if s.get('Effect', '').lower() == 'deny']
    buckets = []

    for i, stmt in enumerate(stmts):
        if stmt.get('Effect', '').lower() != 'allow':
            continue

        # Determine actions and whether NotAction is used
        is_not = 'NotAction' in stmt
        raw_actions = stmt.get('NotAction', stmt.get('Action', []))
        if isinstance(raw_actions, str):
            raw_actions = [raw_actions]

        sid = stmt.get('Sid', f'Statement_{i}')

        # Build modified policy: just this Allow + all Denies
        modified_policy = copy.deepcopy(policy_json)
        modified_policy['Statement'] = [copy.deepcopy(stmt)] + copy.deepcopy(deny_stmts)

        buckets.append({
            'actions': raw_actions,
            'is_not': is_not,
            'sid': sid,
            'policy': modified_policy,
        })

    return buckets


def format_actions(actions, is_not):
    """Format action list for display."""
    s = ', '.join(actions)
    if is_not:
        s = 'NOT(' + s + ')'
    return s


def simplify_regex_with_llm(raw_regex, actions_str, bucket_policy, bound):
    """
    Call Claude Opus 4.6 to simplify a raw DFA regex and generate example resource paths.
    Uses two focused LLM calls:
      1. Regex → simplified regex
      2. Policy + simplified regex → example resource paths

    Returns:
        tuple: (simplified_regex: str, example_paths: list[str])
    """
    import anthropic

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print('        [!] ANTHROPIC_API_KEY not set, skipping LLM explanation')
        return None, []

    client = anthropic.Anthropic(api_key=api_key)

    # --- Call 1: Simplify the regex ---
    prompt1 = f"""You are an expert in AWS IAM policies and regular expressions.

I have a raw regex generated from a DFA (Deterministic Finite Automaton).
This regex represents the set of ALL AWS resource ARNs accessible for these actions: {actions_str}

Raw regex:
{raw_regex}

Simplify this regex into a concise, human-readable form. Use standard regex notation (e.g., .* instead of listing every character). If it matches all strings, just say .*

Respond with ONLY the simplified regex on a single line, nothing else."""

    try:
        resp1 = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=512,
            messages=[{'role': 'user', 'content': prompt1}]
        )
        simplified = resp1.content[0].text.strip()
    except Exception as e:
        print(f'        [!] LLM simplification failed: {e}')
        return None, []

    # --- Call 2: Generate permission set regexes ---
    policy_str = json.dumps(bucket_policy, indent=2)
    prompt2 = f"""You are an expert in AWS IAM policies.

Here is an AWS IAM policy:
```json
{policy_str}
```

The allowed actions are: {actions_str}
The simplified resource regex is: {simplified}

Given this policy and the regex, give me up to 5 permission sets as simplified AWS resource patterns (using * for wildcard and ? for single character) that are DEFINITELY allowed by this policy and match the regex.

Rules:
- Each permission set should be an AWS resource ARN pattern using * and ? wildcards (like AWS IAM Resource syntax)
- These should help a user understand the SCOPE of what this policy permits
- If the regex has distinct sub-patterns (e.g. "folder1/.*" OR "folder2/.*"), give one permission set for EACH sub-pattern
- Keep patterns as general as possible while staying within what the policy allows
- Fewer, more informative patterns are better than many redundant ones

Respond with ONLY the resource patterns, one per line, prefixed with "PERM: ". Nothing else."""

    try:
        resp2 = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=512,
            messages=[{'role': 'user', 'content': prompt2}]
        )
        text2 = resp2.content[0].text.strip()
        examples = []
        for line in text2.split('\n'):
            line = line.strip()
            if line.startswith('PERM:'):
                examples.append(line.split(':', 1)[1].strip())
        return simplified, examples
    except Exception as e:
        print(f'        [!] LLM permission set generation failed: {e}')
        return simplified, []


def verify_resource_path(bucket_policy, resource_path, bucket_actions, args):
    """
    Verify that a specific resource path is allowed by the bucket's policy.
    Creates a test policy with the specific resource and uses Quacky's
    policy comparison to check if the bucket policy subsumes it.

    Returns:
        bool: True if the resource is allowed (bucket subsumes test), False otherwise.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tmp_fd1, tmp_test = tempfile.mkstemp(suffix='.json', prefix='verify_test_')
    tmp_fd2, tmp_bucket = tempfile.mkstemp(suffix='.json', prefix='verify_bucket_')
    os.close(tmp_fd1)
    os.close(tmp_fd2)
    tmp_output = tempfile.mktemp(prefix='verify_out_')

    try:
        # Create a test policy: copy the original Allow statement, only change Resource.
        # Also include all Deny statements so both policies have identical deny rules.
        # This isolates purely the resource dimension in the Allow statement.
        original_allow = bucket_policy['Statement'][0]  # first stmt is always the Allow
        test_stmt = copy.deepcopy(original_allow)
        test_stmt['Resource'] = resource_path
        # Remove NotResource if present since we're setting a specific Resource
        test_stmt.pop('NotResource', None)

        # Gather deny statements from bucket policy
        deny_stmts = [
            copy.deepcopy(s) for s in bucket_policy['Statement'][1:]
            if s.get('Effect', '').lower() == 'deny'
        ]

        test_policy = {
            "Version": bucket_policy.get("Version", "2012-10-17"),
            "Statement": [test_stmt] + deny_stmts
        }

        # Strip Condition elements from both policies before verification.
        # Conditions (e.g. MFA checks) cause ABC to hang in two-policy mode
        # because they introduce extra SMT variables. Since both policies have
        # identical Deny rules and we're only verifying the resource dimension,
        # Conditions are orthogonal and safe to remove here.
        bucket_policy_clean = copy.deepcopy(bucket_policy)
        for stmt in test_policy['Statement']:
            stmt.pop('Condition', None)
        for stmt in bucket_policy_clean['Statement']:
            stmt.pop('Condition', None)

        with open(tmp_test, 'w') as f:
            json.dump(test_policy, f)
        with open(tmp_bucket, 'w') as f:
            json.dump(bucket_policy_clean, f)

        # Run quacky: -p1 test_policy -p2 bucket_policy
        # This checks: "requests allowed by test but NOT by bucket"
        # If UNSAT → bucket subsumes test → resource is allowed
        cmd = [
            sys.executable, os.path.join(script_dir, 'quacky.py'),
            '-p1', tmp_test, '-p2', tmp_bucket,
            '-b', str(args.bound),
            '-o', tmp_output, '-s',
        ]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                              cwd=script_dir)

        # Parse output for "satisfiability: unsat" or "satisfiability: sat"
        for line in proc.stdout.split('\n'):
            if 'satisfiability:' in line:
                return 'unsat' in line
        return False

    except Exception:
        return False
    finally:
        for fpath in [tmp_test, tmp_bucket,
                      tmp_output + '_1.smt2', tmp_output + '_2.smt2']:
            if os.path.exists(fpath):
                os.unlink(fpath)


def explain_bucket(raw_regex, actions_str, bucket_policy, bucket_actions, args):
    """
    Orchestrate LLM simplification + Quacky verification for one bucket.

    Returns:
        tuple: (simplified_regex, verified_examples, failed_examples)
    """
    simplified, examples = simplify_regex_with_llm(raw_regex, actions_str, bucket_policy, args.bound)

    if not simplified and not examples:
        return None, [], []

    verified = []
    failed = []

    for path in examples:
        if verify_resource_path(bucket_policy, path, bucket_actions, args):
            verified.append(path)
        else:
            failed.append(path)

    return simplified, verified, failed


def run_action_buckets(args):
    """
    Run action-bucket summarization for a single policy.
    For each Allow statement, create a modified policy and run the
    full quacky pipeline via subprocess to get the resource regex.
    """
    policy_path = os.path.abspath(args.policy1)
    with open(policy_path) as f:
        policy_json = json.load(f)

    buckets = extract_action_buckets(policy_json)
    policy_name = os.path.basename(policy_path)
    do_explain = getattr(args, 'explain', False)

    print('=' * 70)
    print('Action-Resource Pair Summary')
    print(f'Policy: {policy_name}')
    print(f'Bound:  {args.bound}')
    if do_explain:
        print(f'LLM Explanation: enabled (Claude Opus)')
    print('=' * 70)
    print()

    if not buckets:
        print('No Allow statements found.')
        return

    print(f'Found {len(buckets)} action bucket(s).\n')

    results = []
    total_time = 0
    script_dir = os.path.dirname(os.path.abspath(__file__))

    for i, bucket in enumerate(buckets):
        sid = bucket['sid']
        actions_str = format_actions(bucket['actions'], bucket['is_not'])
        print(f'  [{i+1}/{len(buckets)}] {sid}: {actions_str}')

        # Write modified policy to temp file
        tmp_fd, tmp_policy = tempfile.mkstemp(suffix='.json', prefix='ab_')
        os.close(tmp_fd)
        tmp_output = tempfile.mktemp(prefix='ab_out_')

        try:
            with open(tmp_policy, 'w') as f:
                json.dump(bucket['policy'], f)

            # Build command: run quacky.py with -pr on the modified policy
            cmd = [
                sys.executable, os.path.join(script_dir, 'quacky.py'),
                '-p1', tmp_policy,
                '-b', str(args.bound),
                '-o', tmp_output,
                '-pr',
            ]
            if args.smt_lib:
                cmd.append('-s')
            if args.enc:
                cmd.append('-e')
            if args.constraints:
                cmd.append('-c')

            t0 = time.time()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                  cwd=script_dir)
            elapsed = time.time() - t0
            total_time += elapsed

            # Parse output for regex
            regex = None
            is_unsat = False
            for line in proc.stdout.split('\n'):
                if line.startswith('regex_from_dfa:'):
                    regex = line.split(':', 1)[1].strip()
                if 'satisfiability: unsat' in line:
                    is_unsat = True

            if is_unsat or regex is None:
                print(f'        → UNSAT (no accessible resources) [{elapsed:.2f}s]')
                results.append({
                    'actions': actions_str,
                    'regex': '∅',
                    'simplified': None,
                    'verified': [],
                    'failed': [],
                })
            else:
                # Truncate for display if very long
                display = regex if len(regex) <= 200 else regex[:200] + '...'
                print(f'        → {display} [{elapsed:.2f}s]')

                simplified = None
                verified = []
                failed = []

                if do_explain and regex != '∅':
                    print(f'        🤖 Asking Claude Opus to simplify...')
                    simplified, verified, failed = explain_bucket(
                        regex, actions_str, bucket['policy'], bucket['actions'], args
                    )
                    if simplified:
                        print(f'        📋 Simplified: {simplified}')
                    if verified:
                        for v in verified:
                            print(f'        ✅ {v}')
                    if failed:
                        for f_item in failed:
                            print(f'        ❌ {f_item} (UNSAT — denied by policy)')

                results.append({
                    'actions': actions_str,
                    'regex': regex,
                    'simplified': simplified,
                    'verified': verified,
                    'failed': failed,
                })

        except subprocess.TimeoutExpired:
            print(f'        → TIMEOUT [{elapsed:.2f}s]')
            results.append({
                'actions': actions_str,
                'regex': 'TIMEOUT',
                'simplified': None,
                'verified': [],
                'failed': [],
            })
        finally:
            for fpath in [tmp_policy, tmp_output + '_1.smt2']:
                if os.path.exists(fpath):
                    os.unlink(fpath)

    # Print summary table
    print()
    print('=' * 70)
    print('SUMMARY')
    print('=' * 70)
    for i, r in enumerate(results):
        act = r['actions']
        act_display = act if len(act) <= 65 else act[:63] + '..'
        print(f'\n  [{i+1}] {act_display}')
        if r.get('simplified'):
            print(f'      Simplified regex: {r["simplified"]}')
        else:
            print(f'      Raw regex: {r["regex"]}')
        if r.get('verified'):
            print(f'      Verified examples:')
            for v in r['verified']:
                print(f'        ✅ {v}')
        if r.get('failed'):
            for f_item in r['failed']:
                print(f'        ❌ {f_item} (denied by policy)')
    print()
    print('=' * 70)
    print(f'Total ABC time: {total_time:.2f}s')


def run_query_action(args):
    """
    Query the resource regex for a specific action against the full policy.
    Generates the full SMT formula, injects an action constraint, and
    runs ABC with --print-regex.
    """
    action = args.query_action.lower()
    tmp_output = tempfile.mktemp(prefix='qa_out_')

    # Step 1: Run call_translator to generate the SMT formula
    orig_output = args.output
    args.output = tmp_output
    call_translator(args)
    args.output = orig_output

    smt_file = tmp_output + '_1.smt2'

    try:
        # Step 2: Inject action constraint before (check-sat)
        with open(smt_file, 'r') as f:
            formula = f.read()

        constraint = f'\n; Query action constraint\n(assert (= action "{action}"))\n'
        formula = formula.replace('(check-sat)', constraint + '(check-sat)')

        with open(smt_file, 'w') as f:
            f.write(formula)

        # Step 3: Run ABC with --print-regex
        shell = Shell()
        cmd = 'abc -bs {} -v 0 -i {} --precise --count-tuple --print-regex resource'.format(
            args.bound, smt_file)

        t0 = time.time()
        out, err = shell.runcmd(cmd)
        elapsed = time.time() - t0

        result = get_abc_result_line(out, err)

        print(f'Action: {action}')
        print(f'Time:   {elapsed:.2f}s')

        if result.get('is_sat') == 'unsat':
            print(f'Result: \u2205 (no accessible resources for this action)')
        else:
            regex = result.get('regex_from_dfa', 'N/A')
            print(f'Resource regex: {regex}')

    finally:
        if os.path.exists(smt_file):
            os.unlink(smt_file)


if __name__ == '__main__':
    parser = ap.ArgumentParser(description = 'Quantitatively analyze permissiveness of access control policies')
    parser.add_argument('-p1' , '--policy1'         , help = 'policy 1 (AWS)'               , required = False)
    parser.add_argument('-p2' , '--policy2'         , help = 'policy 2 (AWS)'               , required = False)
    parser.add_argument('-rd' , '--role-definitions', help = 'role definitions (Azure)'     , required = False)
    parser.add_argument('-ra1', '--role-assignment1', help = 'role assignment 1 (Azure)'    , required = False)
    parser.add_argument('-ra2', '--role-assignment2', help = 'role assignment 2 (Azure)'    , required = False)
    parser.add_argument('-r'  , '--roles'           , help = 'roles (GCP)'                  , required = False)
    parser.add_argument('-rb1', '--role-binding1'   , help = 'role binding 1 (GCP)'         , required = False)
    parser.add_argument('-rb2', '--role-binding2'   , help = 'role binding 2 (GCP)'         , required = False)
    # parser.add_argument('-d'  , '--domain'          , help = 'domain file (not supported)'  , required = False)
    parser.add_argument('-o'  , '--output'          , help = 'output file'                  , required = False, default = 'output')
    parser.add_argument('-s'  , '--smt-lib'         , help = 'use SMT-LIB syntax'           , required = False, action = 'store_true')
    parser.add_argument('-e'  , '--enc'             , help = 'use action encoding'          , required = False, action = 'store_true')
    parser.add_argument('-c'  , '--constraints'     , help = 'use resource type constraints', required = False, action = 'store_true')
    parser.add_argument('-b'  , '--bound'           , help = 'bound'                        , required = True , default = 100)
    parser.add_argument('-f'  , '--variable'        , help = 'count all variables'          , required = False, action = 'store_true')
    parser.add_argument('-m'  , '--models'          , help = 'get random number of models'  , required = False)
    parser.add_argument('-m1' , '--minrange'       , help = 'min length of models'         , required = False, default = 0)
    parser.add_argument('-m2' , '--maxrange'       , help = 'max length of models'         , required = False, default = 0)
    parser.add_argument('-pr' , '--printregex'   , help = 'print regex extracted from dfa', required = False, action = 'store_true')
    parser.add_argument('-cr' , '--compareregex'   , help = 'compare given regex resource during policy comparison', required = False)
    parser.add_argument('-cr2' , '--compareregex2'   , help = 'compare given regex resource during policy comparison', required = False)
    parser.add_argument('-v', '--verbose', help = 'Verbose', required = False, action = 'store_true')
    parser.add_argument('-ab', '--action-buckets', help = 'summarize per-action-bucket resource regexes', required = False, action = 'store_true')
    parser.add_argument('-qa', '--query-action', help = 'query resource regex for a specific action', required = False)
    parser.add_argument('-ex', '--explain', help = 'use LLM to simplify regexes and generate verified examples (use with -ab)', required = False, action = 'store_true')


    args = parser.parse_args()

    if args.action_buckets:
        run_action_buckets(args)
    elif args.query_action:
        run_query_action(args)
    else:
        call_translator(args)
        call_abc(args)
