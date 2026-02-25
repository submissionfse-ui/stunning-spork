"""
Mutation Comparator for EC2 Policies

For each (original, mutant) policy pair in samples/ec2/exp_single vs
samples/mutations/ec2/exp_single:

1. Run quacky -p1 <original> -b 100 -p2 <mutant> -pr
   → extracts 0-2 regexes (P1_not_P2, not_P1_P2) and satisfiability for each direction
2. For each SAT direction, use LLM to directly simplify the DFA regex
3. Run quacky -p1 <original> -b 100 -p2 <mutant> -cr <simplified1> -cr2 <simplified2>
   → computes Jaccard similarity for each direction
4. Save results to JSON/CSV and print summary

Usage:
    python3 mutation_comparator.py -q /path/to/quacky.py
    python3 mutation_comparator.py -q /path/to/quacky.py --test
"""

import subprocess
import os
import json
import csv
import argparse
import tempfile
import logging
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

QUACKY_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'quacky', 'src'))
_BASE = os.path.abspath(os.path.dirname(__file__))
SERVICES = {
    'ec2': {
        'originals': os.path.join(_BASE, 'quacky', 'samples', 'ec2', 'exp_single'),
        'mutations': os.path.join(_BASE, 'quacky', 'samples', 'mutations', 'ec2', 'exp_single'),
    },
    'iam': {
        'originals': os.path.join(_BASE, 'quacky', 'samples', 'iam', 'exp_single'),
        'mutations': os.path.join(_BASE, 'quacky', 'samples', 'mutations', 'iam', 'exp_single'),
    },
    's3': {
        'originals': os.path.join(_BASE, 'quacky', 'samples', 's3', 'exp_single'),
        'mutations': os.path.join(_BASE, 'quacky', 'samples', 'mutations', 's3', 'exp_single'),
    },
}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(log_file=None, verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = []

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)
        logging.info(f"Logging to: {log_file}")


# ---------------------------------------------------------------------------
# Policy pair discovery
# ---------------------------------------------------------------------------

def discover_pairs():
    """
    Return a list of (label, original_path, mutant_path) tuples for all
    (service, policy, variant) combinations that have both an original and mutations.

    Layout expected:
        mutations/<service>/exp_single/<policy>/<variant>/<N_M>.json
        samples/<service>/exp_single/<policy>/<variant>.json

    The variant subdir name (e.g. 'policy', 'fixed', 'initial', 'policy1') must
    match the original filename without extension.
    """
    pairs = []
    for service, dirs in SERVICES.items():
        mutations_dir = dirs['mutations']
        originals_dir = dirs['originals']

        if not os.path.isdir(mutations_dir):
            logging.warning(f"Mutations directory not found: {mutations_dir}")
            continue

        for policy_name in sorted(os.listdir(mutations_dir)):
            policy_mut_base = os.path.join(mutations_dir, policy_name)
            if not os.path.isdir(policy_mut_base):
                continue

            for variant_name in sorted(os.listdir(policy_mut_base)):
                variant_dir = os.path.join(policy_mut_base, variant_name)
                if not os.path.isdir(variant_dir):
                    continue

                original = os.path.join(originals_dir, policy_name, f'{variant_name}.json')
                if not os.path.exists(original):
                    logging.warning(
                        f"No original found for {service}/{policy_name}/{variant_name} "
                        f"(expected {original}), skipping"
                    )
                    continue

                label = f"{service}/{policy_name}/{variant_name}"
                for mutant_file in sorted(os.listdir(variant_dir)):
                    if mutant_file.endswith('.json'):
                        mutant_path = os.path.join(variant_dir, mutant_file)
                        pairs.append((label, original, mutant_path))

    return pairs


# ---------------------------------------------------------------------------
# Quacky runners
# ---------------------------------------------------------------------------

def run_quacky_extract(quacky_path, p1, p2, bound=100):
    """
    Run: python3 quacky.py -p1 <p1> -b <bound> -p2 <p2> -pr
    Returns raw stdout + stderr.
    """
    cmd = [
        'python3', os.path.abspath(quacky_path),
        '-p1', os.path.abspath(p1),
        '-b', str(bound),
        '-p2', os.path.abspath(p2),
        '-pr',
    ]
    logging.debug(f"Extract cmd: {' '.join(cmd)}")
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=os.path.dirname(os.path.abspath(quacky_path)), timeout=100
    )
    logging.debug(f"Extract stdout:\n{result.stdout}")
    if result.stderr:
        logging.debug(f"Extract stderr:\n{result.stderr}")
    return result.stdout, result.stderr


def run_quacky_compare(quacky_path, p1, p2, bound=100, cr_file=None, cr2_file=None):
    """
    Run: python3 quacky.py -p1 <p1> -b <bound> -p2 <p2> [-cr <f1>] [-cr2 <f2>]
    Returns raw stdout + stderr.
    """
    cmd = [
        'python3', os.path.abspath(quacky_path),
        '-p1', os.path.abspath(p1),
        '-b', str(bound),
        '-p2', os.path.abspath(p2),
    ]
    if cr_file:
        cmd += ['-cr', os.path.abspath(cr_file)]
    if cr2_file:
        cmd += ['-cr2', os.path.abspath(cr2_file)]

    logging.debug(f"Compare cmd: {' '.join(cmd)}")
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=os.path.dirname(os.path.abspath(quacky_path)), timeout=300
    )
    logging.debug(f"Compare stdout:\n{result.stdout}")
    if result.stderr:
        logging.debug(f"Compare stderr:\n{result.stderr}")
    return result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Output parsers
# ---------------------------------------------------------------------------

def parse_extract_output(stdout, stderr):
    """
    Parse the stdout of a quacky -pr run with two policies.

    Returns:
        {
          'p1_not_p2': {'satisfiability': str, 'regex': str|None},
          'not_p1_p2': {'satisfiability': str, 'regex': str|None},
          'verdict': str,
          'raw_stdout': str,
          'raw_stderr': str,
        }
    """
    result = {
        'p1_not_p2': {'satisfiability': None, 'regex': None},
        'not_p1_p2': {'satisfiability': None, 'regex': None},
        'verdict': None,
        'raw_stdout': stdout,
        'raw_stderr': stderr,
    }

    # Split into sections by header markers
    section1_lines = []
    section2_lines = []
    current = None

    for line in stdout.split('\n'):
        stripped = line.strip()
        if 'Policy 1 ⇏ Policy 2' in stripped or 'Policy 1 \u21cf Policy 2' in stripped:
            current = 'p1_not_p2'
            continue
        if 'Policy 2 ⇏ Policy 1' in stripped or 'Policy 2 \u21cf Policy 1' in stripped:
            current = 'not_p1_p2'
            continue
        if stripped.startswith('Policy 1 and Policy 2') or stripped.startswith('Policy 1 is'):
            result['verdict'] = stripped
            current = None
            continue

        if current == 'p1_not_p2':
            section1_lines.append(stripped)
        elif current == 'not_p1_p2':
            section2_lines.append(stripped)

    def parse_section(lines, key):
        for line in lines:
            if line.startswith('satisfiability:'):
                result[key]['satisfiability'] = line.split(':', 1)[1].strip()
            elif line.startswith('regex_from_dfa:'):
                result[key]['regex'] = line.split(':', 1)[1].strip()

    parse_section(section1_lines, 'p1_not_p2')
    parse_section(section2_lines, 'not_p1_p2')

    return result


def parse_compare_section(lines):
    """Parse comparison metrics from a block of output lines."""
    metrics = {
        'satisfiability': None,
        'baseline_regex_count': None,
        'synthesized_regex_count': None,
        'jaccard_numerator': None,
        'jaccard_denominator': None,
        'jaccard_similarity': None,
    }
    for line in lines:
        line = line.strip()
        if line.startswith('satisfiability:'):
            metrics['satisfiability'] = line.split(':', 1)[1].strip()
        elif line.startswith('Baseline Regex Count'):
            metrics['baseline_regex_count'] = line.split(':', 1)[1].strip()
        elif line.startswith('Synthesized Regex Count'):
            metrics['synthesized_regex_count'] = line.split(':', 1)[1].strip()
        elif line.startswith('jaccard_numerator'):
            metrics['jaccard_numerator'] = line.split(':', 1)[1].strip()
        elif line.startswith('jaccard_denominator'):
            metrics['jaccard_denominator'] = line.split(':', 1)[1].strip()
        elif line.startswith('similarity1') or line.startswith('similarity2'):
            metrics['jaccard_similarity'] = line.split(':', 1)[1].strip()
    return metrics


def parse_compare_output(stdout, stderr):
    """
    Parse stdout of a quacky compare run (with -cr / -cr2).

    Returns:
        {
          'p1_not_p2': { metrics... },
          'not_p1_p2': { metrics... },
          'raw_stdout': str,
          'raw_stderr': str,
        }
    """
    result = {
        'p1_not_p2': parse_compare_section([]),
        'not_p1_p2': parse_compare_section([]),
        'raw_stdout': stdout,
        'raw_stderr': stderr,
    }

    section1_lines = []
    section2_lines = []
    current = None

    for line in stdout.split('\n'):
        stripped = line.strip()
        if 'Policy 1 ⇏ Policy 2' in stripped or 'Policy 1 \u21cf Policy 2' in stripped:
            current = 'p1_not_p2'
            continue
        if 'Policy 2 ⇏ Policy 1' in stripped or 'Policy 2 \u21cf Policy 1' in stripped:
            current = 'not_p1_p2'
            continue
        if stripped.startswith('Policy 1 and Policy 2') or stripped.startswith('Policy 1 is'):
            current = None
            continue
        if current == 'p1_not_p2':
            section1_lines.append(stripped)
        elif current == 'not_p1_p2':
            section2_lines.append(stripped)

    result['p1_not_p2'] = parse_compare_section(section1_lines)
    result['not_p1_p2'] = parse_compare_section(section2_lines)
    return result


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

def prompt_llm_for_simplification(regex, client, retry_context=None):
    """Ask the LLM to produce a simplified equivalent regex."""
    if retry_context:
        prompt = f"""You are an expert in regular expressions and cloud security policies.

You previously generated a simplified regex, but it did NOT match the same resources as the original.

ORIGINAL DFA REGEX:
{regex}

YOUR PREVIOUS ATTEMPT:
{retry_context['previous_regex']}

COMPARISON RESULTS:
- Original regex matched: {retry_context['baseline_count']} resources
- Your regex matched: {retry_context['synthesized_count']} resources
- Jaccard Similarity: {retry_context['jaccard_similarity']} (should be close to 1.0)

ANALYSIS:
- If your regex matched FEWER resources, you were TOO RESTRICTIVE. Make it more permissive.
- If your regex matched MORE resources, you were TOO PERMISSIVE. Make it more restrictive.

Please generate a NEW simplified regex that is semantically equivalent to the original.

IMPORTANT: Respond with ONLY the corrected regex on a single line. No explanation, no markdown, no backticks, no anchors (^ or $).
Give the output as a raw regex. Do not assume this regex will be used in Python or any standard regex engine. Output a plain, raw regex pattern as would be used with grep or sed."""
    else:
        prompt = f"""You are an expert in regular expressions and cloud security policies.

Given the following regex extracted from a DFA representing cloud resource access patterns:

{regex}

Please generate a SIMPLIFIED, human-readable equivalent regex that matches the same resources.

Make it shorter and more readable while preserving the exact semantic meaning.

IMPORTANT: Respond with ONLY the simplified regex on a single line. No explanation, no markdown, no backticks, no anchors (^ or $).
Give the output as a raw regex. Do not assume this regex will be used in Python or any standard regex engine. Output a plain, raw regex pattern as would be used with grep or sed."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    regex_result = message.content[0].text.strip()

    if regex_result.startswith('^'):
        regex_result = regex_result[1:]
    if regex_result.endswith('$'):
        regex_result = regex_result[:-1]

    return regex_result


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def write_results_json(results, path):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as f:
        json.dump(results, f, indent=2)
    logging.info(f"Results written to JSON: {path}")


def write_results_csv(results, path):
    if not results:
        return
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    fieldnames = [
        'policy_name', 'mutant_file',
        'p1_not_p2_sat', 'p1_not_p2_regex_dfa', 'p1_not_p2_regex_llm',
        'p1_not_p2_jaccard',
        'not_p1_p2_sat', 'not_p1_p2_regex_dfa', 'not_p1_p2_regex_llm',
        'not_p1_p2_jaccard',
        'verdict', 'error',
    ]
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)
    logging.info(f"Results written to CSV: {path}")


def print_summary(results):
    total = len(results)
    if total == 0:
        logging.info("No results.")
        return

    p1_not_p2_unsat = sum(1 for r in results if r.get('p1_not_p2_sat') == 'unsat')
    not_p1_p2_unsat = sum(1 for r in results if r.get('not_p1_p2_sat') == 'unsat')
    both_unsat = sum(
        1 for r in results
        if r.get('p1_not_p2_sat') == 'unsat' and r.get('not_p1_p2_sat') == 'unsat'
    )
    errors = sum(1 for r in results if r.get('error'))

    logging.info("")
    logging.info("=" * 60)
    logging.info("SUMMARY")
    logging.info("=" * 60)
    logging.info(f"Total pairs processed : {total}")
    logging.info(f"Errors                : {errors}")
    logging.info("")
    logging.info(f"P1_not_P2  UNSAT      : {p1_not_p2_unsat} / {total}  "
                 f"(original ⊆ mutant, i.e. mutant is more permissive)")
    logging.info(f"not_P1_P2  UNSAT      : {not_p1_p2_unsat} / {total}  "
                 f"(mutant ⊆ original, i.e. original is more permissive)")
    logging.info(f"Both UNSAT (equiv)    : {both_unsat} / {total}")

    # Jaccard stats for pairs where comparison was done
    def jaccard_stats(key):
        vals = []
        for r in results:
            v = r.get(key)
            if v is not None:
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    pass
        if vals:
            return f"n={len(vals)}, avg={sum(vals)/len(vals):.3f}, min={min(vals):.3f}, max={max(vals):.3f}"
        return "n=0"

    logging.info("")
    logging.info(f"P1_not_P2  Jaccard    : {jaccard_stats('p1_not_p2_jaccard')}")
    logging.info(f"not_P1_P2  Jaccard    : {jaccard_stats('not_p1_p2_jaccard')}")


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_pairs(quacky_path, bound=100, output_dir='results', test_mode=False):
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        logging.error("ANTHROPIC_API_KEY not set.")
        return []
    if not HAS_ANTHROPIC:
        logging.error("anthropic package not installed. Run: pip install anthropic")
        return []

    client = anthropic.Anthropic(api_key=api_key)

    pairs = discover_pairs()
    # label is "service/policy/variant"; count unique service/policy prefixes
    unique_policies = len(set('/'.join(p[0].split('/')[:2]) for p in pairs))
    logging.info(f"Discovered {len(pairs)} (original, mutant) pairs across "
                 f"{unique_policies} policies")

    if test_mode:
        pairs = pairs[:3]
        logging.info(f"TEST MODE: running only {len(pairs)} pairs")

    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, 'mutation_results.json')
    csv_path  = os.path.join(output_dir, 'mutation_results.csv')

    # Resume from existing results
    results = []
    done_keys = set()
    if os.path.exists(json_path):
        try:
            with open(json_path) as f:
                results = json.load(f)

            def is_complete(r):
                """True if all expected Jaccard values are satisfactory (or the entry errored/exhausted)."""
                if r.get('error'):
                    return True

                def jaccard_ok(val):
                    try:
                        return float(val) >= 0.9
                    except (ValueError, TypeError):
                        return False

                p1_done = (r.get('p1_not_p2_sat') != 'sat' or
                           r.get('p1_not_p2_jaccard') is not None)
                p2_done = (r.get('not_p1_p2_sat') != 'sat' or
                           r.get('not_p1_p2_jaccard') is not None)
                return p1_done and p2_done

            complete = [r for r in results if is_complete(r)]
            incomplete = len(results) - len(complete)
            if incomplete:
                logging.info(f"Re-processing {incomplete} entries with missing Jaccard values")
            results = complete
            done_keys = {(r['policy_name'], r['mutant_file']) for r in results}
            logging.info(f"Resuming: {len(results)} already complete")
        except Exception as e:
            logging.warning(f"Could not load existing results: {e}")

    temp_dir = tempfile.mkdtemp(prefix='mutation_comparator_')

    try:
        for idx, (policy_name, original_path, mutant_path) in enumerate(pairs):
            mutant_file = os.path.basename(mutant_path)
            key = (policy_name, mutant_file)

            logging.info("")
            logging.info(f"[{idx+1}/{len(pairs)}] {policy_name} / {mutant_file}")

            if key in done_keys:
                logging.info("  SKIP: already processed")
                continue

            record = {
                'policy_name': policy_name,
                'mutant_file': mutant_file,
                'p1_not_p2_sat': None,
                'p1_not_p2_regex_dfa': None,
                'p1_not_p2_regex_llm': None,
                'p1_not_p2_jaccard': None,
                'not_p1_p2_sat': None,
                'not_p1_p2_regex_dfa': None,
                'not_p1_p2_regex_llm': None,
                'not_p1_p2_jaccard': None,
                'verdict': None,
                'error': None,
            }

            # ------------------------------------------------------------------
            # Step 1: Extract regexes
            # ------------------------------------------------------------------
            try:
                stdout, stderr = run_quacky_extract(quacky_path, original_path, mutant_path, bound)
                extract = parse_extract_output(stdout, stderr)
            except Exception as e:
                logging.error(f"  Extract failed: {e}")
                record['error'] = f"extract error: {e}"
                results.append(record)
                write_results_json(results, json_path)
                write_results_csv(results, csv_path)
                continue

            p1_sat   = extract['p1_not_p2']['satisfiability']
            p1_regex = extract['p1_not_p2']['regex']
            p2_sat   = extract['not_p1_p2']['satisfiability']
            p2_regex = extract['not_p1_p2']['regex']

            record['p1_not_p2_sat']      = p1_sat
            record['p1_not_p2_regex_dfa'] = p1_regex
            record['not_p1_p2_sat']      = p2_sat
            record['not_p1_p2_regex_dfa'] = p2_regex
            record['verdict']             = extract['verdict']

            logging.info(f"  P1_not_P2:  {p1_sat}  |  not_P1_P2: {p2_sat}")

            # ------------------------------------------------------------------
            # Step 2: LLM simplification — for each SAT direction independently
            # ------------------------------------------------------------------
            cr_file  = None
            cr2_file = None

            safe_name = policy_name.replace('/', '_')

            if p1_sat == 'sat' or p2_sat == 'sat':
                # ----------------------------------------------------------
                # P1_not_P2 direction: LLM + compare with up to 2 retries
                # ----------------------------------------------------------
                if p1_sat == 'sat' and p1_regex:
                    retry_context = None
                    for attempt in range(2):
                        try:
                            logging.info(f"  LLM simplifying P1_not_P2 regex (attempt {attempt+1}/2)...")
                            llm_regex = prompt_llm_for_simplification(p1_regex, client, retry_context)
                            record['p1_not_p2_regex_llm'] = llm_regex
                            cr_path = os.path.join(temp_dir, f'{safe_name}_{mutant_file}_cr1.txt')
                            with open(cr_path, 'w') as f:
                                f.write(llm_regex)
                            cr_file = cr_path

                            cmp_stdout, cmp_stderr = run_quacky_compare(
                                quacky_path, original_path, mutant_path, bound, cr_file, None
                            )
                            cmp = parse_compare_output(cmp_stdout, cmp_stderr)
                            jaccard = cmp['p1_not_p2'].get('jaccard_similarity')
                            record['p1_not_p2_jaccard'] = jaccard
                            logging.info(f"  P1_not_P2 Jaccard: {jaccard}")

                            try:
                                sim = float(jaccard) if jaccard is not None else 0.0
                            except (ValueError, TypeError):
                                sim = 0.0

                            if sim >= 0.9 or attempt == 1:
                                break
                            logging.warning(f"  P1_not_P2 Jaccard is {jaccard}, retrying with feedback...")
                            retry_context = {
                                'previous_regex': llm_regex,
                                'baseline_count': cmp['p1_not_p2'].get('baseline_regex_count'),
                                'synthesized_count': cmp['p1_not_p2'].get('synthesized_regex_count'),
                                'jaccard_similarity': jaccard,
                            }
                        except Exception as e:
                            logging.error(f"  P1_not_P2 attempt {attempt+1} failed: {e}")
                            break

                # ----------------------------------------------------------
                # not_P1_P2 direction: LLM + compare with up to 2 retries
                # ----------------------------------------------------------
                if p2_sat == 'sat' and p2_regex:
                    retry_context = None
                    for attempt in range(2):
                        try:
                            logging.info(f"  LLM simplifying not_P1_P2 regex (attempt {attempt+1}/2)...")
                            llm_regex2 = prompt_llm_for_simplification(p2_regex, client, retry_context)
                            record['not_p1_p2_regex_llm'] = llm_regex2
                            cr2_path = os.path.join(temp_dir, f'{safe_name}_{mutant_file}_cr2.txt')
                            with open(cr2_path, 'w') as f:
                                f.write(llm_regex2)
                            cr2_file = cr2_path

                            cmp_stdout, cmp_stderr = run_quacky_compare(
                                quacky_path, original_path, mutant_path, bound, None, cr2_file
                            )
                            cmp = parse_compare_output(cmp_stdout, cmp_stderr)
                            jaccard2 = cmp['not_p1_p2'].get('jaccard_similarity')
                            record['not_p1_p2_jaccard'] = jaccard2
                            logging.info(f"  not_P1_P2 Jaccard: {jaccard2}")

                            try:
                                sim2 = float(jaccard2) if jaccard2 is not None else 0.0
                            except (ValueError, TypeError):
                                sim2 = 0.0

                            if sim2 >= 0.9 or attempt == 1:
                                break
                            logging.warning(f"  not_P1_P2 Jaccard is {jaccard2}, retrying with feedback...")
                            retry_context = {
                                'previous_regex': llm_regex2,
                                'baseline_count': cmp['not_p1_p2'].get('baseline_regex_count'),
                                'synthesized_count': cmp['not_p1_p2'].get('synthesized_regex_count'),
                                'jaccard_similarity': jaccard2,
                            }
                        except Exception as e:
                            logging.error(f"  not_P1_P2 attempt {attempt+1} failed: {e}")
                            break
            else:
                logging.info("  Skipping LLM: both directions UNSAT (policies are equivalent)")

            results.append(record)
            write_results_json(results, json_path)
            write_results_csv(results, csv_path)
            logging.info(f"  Progress saved ({len(results)} total)")

    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    print_summary(results)
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Compare original EC2 policies against their mutants using Quacky + LLM'
    )
    parser.add_argument('-q', '--quacky', required=True, help='Path to quacky.py')
    parser.add_argument('-b', '--bound', type=int, default=100, help='Quacky bound (default: 100)')
    parser.add_argument('-o', '--output-dir', default='results', help='Output directory (default: results)')
    parser.add_argument('--test', action='store_true', help='Test mode: process only 3 pairs')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose debug output')
    parser.add_argument('--log', help='Log file path')
    args = parser.parse_args()

    log_file = args.log
    if args.test and not log_file:
        log_file = f"mutation_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    setup_logging(log_file=log_file, verbose=args.verbose)

    logging.info("=" * 60)
    logging.info("Mutation Comparator")
    logging.info("=" * 60)
    logging.info(f"Quacky path : {args.quacky}")
    logging.info(f"Bound       : {args.bound}")
    logging.info(f"Output dir  : {args.output_dir}")
    logging.info(f"Test mode   : {args.test}")
    logging.info(f"Started at  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    process_pairs(
        quacky_path=args.quacky,
        bound=args.bound,
        output_dir=args.output_dir,
        test_mode=args.test,
    )

    logging.info(f"\nFinished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if log_file:
        logging.info(f"Log saved to: {log_file}")


if __name__ == '__main__':
    main()
