"""
Regex Summarizer (Regex-Based Approach) for Cloud Policies

This script uses the REGEX-BASED approach:
1. Processes AWS policies, Azure role definitions/assignments, and GCP roles/bindings
2. Runs Quacky to extract regex from DFA (regex_from_dfa)
3. Prompts an LLM to generate a summarized/simplified equivalent regex
4. Writes the LLM regex to a file
5. Runs Quacky again with --compareregex to compute Jaccard similarity using ABC
6. Outputs results in both CSV and JSON formats

Usage:
    # AWS test mode
    python3 regex_summarizer_regex_based.py --test -q /path/to/quacky.py -apd ./aws/

    # Azure test mode
    python3 regex_summarizer_regex_based.py --test -q /path/to/quacky.py -ard role_def.json -aad ./assignments/

    # Full run with custom output path
    python3 regex_summarizer_regex_based.py -q /path/to/quacky.py -ard role_def.json -aad ./assignments/ -o results/output.csv
"""

import subprocess
import re
import os
import json
import argparse
import csv
import tempfile
import logging
import sys
from pathlib import Path
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()


try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


def setup_logging(log_file: str = None, verbose: bool = False):
    """Setup logging to both file and console."""
    log_level = logging.DEBUG if verbose else logging.INFO

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Setup root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Clear existing handlers
    logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logging.info(f"Logging to file: {log_file}")

    return logger


def run_quacky_aws_extract(quacky_path: str, policy_file: str, bound: int = 250) -> dict:
    """
    Run Quacky on an AWS policy to get regex.

    Returns:
        dict with solve_time, satisfiability, count_time, lg_requests, regex_from_dfa
    """
    cmd = [
        'python3', quacky_path,
        '-p1', os.path.abspath(policy_file),
        '-b', str(bound),
        '-pr'
    ]

    logging.debug(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(quacky_path))
    logging.debug(f"STDOUT:\n{result.stdout}")
    if result.stderr:
        logging.debug(f"STDERR:\n{result.stderr}")
    return parse_quacky_extract_output(result.stdout, result.stderr)


def run_quacky_aws_compare(quacky_path: str, policy_file: str,
                            llm_regex_file: str, bound: int = 250) -> dict:
    """
    Run Quacky with --compareregex to compare DFA regex against LLM regex for AWS.

    Returns:
        dict with comparison metrics including Jaccard similarity
    """
    cmd = [
        'python3', quacky_path,
        '-p1', os.path.abspath(policy_file),
        '-b', str(bound),
        '-pr',
        '-cr', os.path.abspath(llm_regex_file)
    ]

    logging.debug(f"Running compare command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(quacky_path))
    logging.debug(f"Compare STDOUT:\n{result.stdout}")
    if result.stderr:
        logging.debug(f"Compare STDERR:\n{result.stderr}")
    return parse_quacky_compare_output(result.stdout, result.stderr)


def run_quacky_azure_extract(quacky_path: str, role_def: str, role_assignment: str, bound: int = 250) -> dict:
    """
    Run Quacky on an Azure role definition and assignment to get regex.

    Returns:
        dict with solve_time, satisfiability, count_time, lg_requests, regex_from_dfa
    """
    cmd = [
        'python3', quacky_path,
        '-rd', role_def,
        '-ra1', role_assignment,
        '-b', str(bound),
        '-pr'
    ]

    logging.debug(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(quacky_path))
    logging.debug(f"STDOUT:\n{result.stdout}")
    if result.stderr:
        logging.debug(f"STDERR:\n{result.stderr}")
    return parse_quacky_extract_output(result.stdout, result.stderr)


def run_quacky_gcp_extract(quacky_path: str, roles: str, role_binding: str, bound: int = 250) -> dict:
    """
    Run Quacky on GCP roles and role binding to get regex.

    Returns:
        dict with solve_time, satisfiability, count_time, lg_requests, regex_from_dfa
    """
    cmd = [
        'python3', quacky_path,
        '-r', roles,
        '-rb1', role_binding,
        '-b', str(bound),
        '-pr'
    ]

    logging.debug(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(quacky_path))
    logging.debug(f"STDOUT:\n{result.stdout}")
    if result.stderr:
        logging.debug(f"STDERR:\n{result.stderr}")
    return parse_quacky_extract_output(result.stdout, result.stderr)


def run_quacky_azure_compare(quacky_path: str, role_def: str, role_assignment: str,
                              llm_regex_file: str, bound: int = 250) -> dict:
    """
    Run Quacky with --compareregex to compare DFA regex against LLM regex.

    Returns:
        dict with comparison metrics including Jaccard similarity
    """
    cmd = [
        'python3', quacky_path,
        '-rd', role_def,
        '-ra1', role_assignment,
        '-b', str(bound),
        '-pr',
        '-cr', llm_regex_file
    ]

    logging.debug(f"Running compare command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(quacky_path))
    logging.debug(f"Compare STDOUT:\n{result.stdout}")
    if result.stderr:
        logging.debug(f"Compare STDERR:\n{result.stderr}")
    return parse_quacky_compare_output(result.stdout, result.stderr)


def run_quacky_gcp_compare(quacky_path: str, roles: str, role_binding: str,
                           llm_regex_file: str, bound: int = 250) -> dict:
    """
    Run Quacky with --compareregex to compare DFA regex against LLM regex.

    Returns:
        dict with comparison metrics including Jaccard similarity
    """
    cmd = [
        'python3', quacky_path,
        '-r', roles,
        '-rb1', role_binding,
        '-b', str(bound),
        '-pr',
        '-cr', llm_regex_file
    ]

    logging.debug(f"Running compare command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.path.dirname(quacky_path))
    logging.debug(f"Compare STDOUT:\n{result.stdout}")
    if result.stderr:
        logging.debug(f"Compare STDERR:\n{result.stderr}")
    return parse_quacky_compare_output(result.stdout, result.stderr)


def parse_quacky_extract_output(stdout: str, stderr: str) -> dict:
    """
    Parse Quacky stdout to extract metrics and regex (first run without --compareregex).
    """
    result = {
        'solve_time': None,
        'satisfiability': None,
        'count_time': None,
        'lg_requests': None,
        'regex_from_dfa': None,
        'raw_stdout': stdout,
        'raw_stderr': stderr
    }

    for line in stdout.split('\n'):
        line = line.strip()

        if line.startswith('Solve Time (ms):'):
            result['solve_time'] = line.split(':', 1)[1].strip()
        elif line.startswith('satisfiability:'):
            result['satisfiability'] = line.split(':', 1)[1].strip()
        elif line.startswith('Count Time (ms):'):
            result['count_time'] = line.split(':', 1)[1].strip()
        elif line.startswith('lg(requests):'):
            result['lg_requests'] = line.split(':', 1)[1].strip()
        elif line.startswith('regex_from_dfa:'):
            result['regex_from_dfa'] = line.split(':', 1)[1].strip()

    return result


def parse_quacky_compare_output(stdout: str, stderr: str) -> dict:
    """
    Parse Quacky stdout when --compareregex is used.
    Extracts Jaccard similarity and other comparison metrics.
    """
    result = {
        'solve_time': None,
        'satisfiability': None,
        'count_time': None,
        'lg_requests': None,
        'regex_from_dfa': None,
        'regex_from_llm': None,
        'baseline_regex_count': None,
        'synthesized_regex_count': None,
        'jaccard_numerator': None,
        'jaccard_denominator': None,
        'jaccard_similarity': None,
        'ops_regex_from_dfa': None,
        'ops_regex_from_llm': None,
        'length_regex_from_dfa': None,
        'length_regex_from_llm': None,
        'raw_stdout': stdout,
        'raw_stderr': stderr
    }

    for line in stdout.split('\n'):
        line = line.strip()

        if line.startswith('Solve Time (ms):'):
            result['solve_time'] = line.split(':', 1)[1].strip()
        elif line.startswith('satisfiability:'):
            result['satisfiability'] = line.split(':', 1)[1].strip()
        elif line.startswith('Count Time (ms):'):
            result['count_time'] = line.split(':', 1)[1].strip()
        elif line.startswith('lg(requests):'):
            result['lg_requests'] = line.split(':', 1)[1].strip()
        elif line.startswith('regex_from_dfa'):
            val = line.split(':', 1)[1].strip()
            result['regex_from_dfa'] = val
        elif line.startswith('regex_from_llm'):
            val = line.split(':', 1)[1].strip()
            result['regex_from_llm'] = val
        elif line.startswith('Baseline Regex Count'):
            result['baseline_regex_count'] = line.split(':', 1)[1].strip()
        elif line.startswith('Synthesized Regex Count'):
            result['synthesized_regex_count'] = line.split(':', 1)[1].strip()
        elif line.startswith('jaccard_numerator'):
            result['jaccard_numerator'] = line.split(':', 1)[1].strip()
        elif line.startswith('jaccard_denominator'):
            result['jaccard_denominator'] = line.split(':', 1)[1].strip()
        elif line.startswith('similarity1'):
            result['jaccard_similarity'] = line.split(':', 1)[1].strip()
        elif line.startswith('ops_regex_from_dfa'):
            result['ops_regex_from_dfa'] = line.split(':', 1)[1].strip()
        elif line.startswith('ops_regex_from_llm'):
            result['ops_regex_from_llm'] = line.split(':', 1)[1].strip()
        elif line.startswith('length_regex_from_dfa'):
            result['length_regex_from_dfa'] = line.split(':', 1)[1].strip()
        elif line.startswith('length_regex_from_llm'):
            result['length_regex_from_llm'] = line.split(':', 1)[1].strip()

    return result


def prompt_llm_for_summary(regex: str, client, retry_context: dict = None, policy_content: str = None) -> str:
    """
    Prompt an LLM to generate a summarized equivalent regex.

    Args:
        regex: The original regex from DFA
        client: Anthropic client
        retry_context: Optional dict with previous attempt info (for retries)
            - previous_regex: The previous LLM regex that failed
            - baseline_count: Count from DFA regex
            - synthesized_count: Count from previous LLM regex
            - jaccard_similarity: Previous similarity score
        policy_content: Optional raw policy JSON string for semantic context

    Returns:
        Summarized regex from LLM
    """
    policy_section = ""
    if policy_content:
        policy_section = f"""
ORIGINAL POLICY (for semantic context):
{policy_content}

"""

    if retry_context:

        prompt = f"""You are an expert in regular expressions and cloud security policies.

You previously generated a simplified regex, but it did NOT match the same resources as the original.
{policy_section}
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
        # Initial prompt
        prompt = f"""You are an expert in regular expressions and cloud security policies.
{policy_section}
Given the following regex extracted from a DFA representing cloud resource access patterns:

{regex}

Please generate a SIMPLIFIED, human-readable equivalent regex that matches the same resources.

Make it shorter and more readable while preserving the exact semantic meaning.

IMPORTANT: Respond with ONLY the simplified regex on a single line. No explanation, no markdown, no backticks, no anchors (^ or $).
Give the output as a raw regex. Do not assume this regex will be used in Python or any standard regex engine. Output a plain, raw regex pattern as would be used with grep or sed."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    regex_result = message.content[0].text.strip()

    # Strip anchors if present (as a safety measure)
    if regex_result.startswith('^'):
        regex_result = regex_result[1:]
    if regex_result.endswith('$'):
        regex_result = regex_result[:-1]

    return regex_result


def is_valid_perl_regex(regex: str) -> bool:
    """Check if a regex is syntactically valid using grep -P (like echo "" | grep -P "regex")."""
    try:
        p1 = subprocess.Popen(['echo', ''], stdout=subprocess.PIPE)
        p2 = subprocess.run(['grep', '-P', regex], stdin=p1.stdout,
                            capture_output=True, text=True)
        p1.wait()
        # grep exits with code 2 if the pattern is invalid
        return p2.returncode != 2
    except Exception:
        return True  # assume valid if check fails


def find_policy_files(base_dir: str, cloud_type: str, max_files: int = 100, test_mode: bool = False) -> list:
    """
    Find policy files in the given directory or return single file if path is a file.

    Args:
        base_dir: Directory to search OR path to a single file
        cloud_type: 'azure' or 'gcp'
        max_files: Maximum number of files to look for (0 to max_files-1)
        test_mode: If True, return only the first file found

    Returns:
        List of file paths
    """
    files = []

    # Check if base_dir is actually a file (not a directory)
    if os.path.isfile(base_dir):
        logging.info(f"Single file provided: {base_dir}")
        return [base_dir]

    # It's a directory, search for files
    if not os.path.isdir(base_dir):
        logging.error(f"Path does not exist: {base_dir}")
        return files

    if cloud_type == 'aws':
        # Look for aws0.json through aws{max_files-1}.json
        for i in range(max_files):
            policy_file = os.path.join(base_dir, f'aws{i}.json')
            if os.path.exists(policy_file):
                files.append(policy_file)
                logging.debug(f"Found AWS policy: {policy_file}")
                if test_mode:
                    break

        # If no awsX.json files found, look for any .json files
        if not files:
            logging.info(f"No aws*.json files found in {base_dir}, searching for any .json files...")
            for f in sorted(os.listdir(base_dir)):
                if f.endswith('.json'):
                    files.append(os.path.join(base_dir, f))
                    logging.debug(f"Found AWS policy: {f}")
                    if test_mode:
                        break

    elif cloud_type == 'azure':
        # Look for as0.json through as{max_files-1}.json
        for i in range(max_files):
            assignment_file = os.path.join(base_dir, f'as{i}.json')
            if os.path.exists(assignment_file):
                files.append(assignment_file)
                logging.debug(f"Found Azure assignment: {assignment_file}")
                if test_mode:
                    break

        # If no asX.json files found, look for any .json files
        if not files:
            logging.info(f"No as*.json files found in {base_dir}, searching for any .json files...")
            for f in sorted(os.listdir(base_dir)):
                if f.endswith('.json'):
                    files.append(os.path.join(base_dir, f))
                    logging.debug(f"Found Azure assignment: {f}")
                    if test_mode:
                        break

    elif cloud_type == 'gcp':
        # Look for bd0.json through bd{max_files-1}.json
        for i in range(max_files):
            binding_file = os.path.join(base_dir, f'bd{i}.json')
            if os.path.exists(binding_file):
                files.append(binding_file)
                logging.debug(f"Found GCP binding: {binding_file}")
                if test_mode:
                    break

        # If no bdX.json files found, look for any .json files
        if not files:
            logging.info(f"No bd*.json files found in {base_dir}, searching for any .json files...")
            for f in sorted(os.listdir(base_dir)):
                if f.endswith('.json'):
                    files.append(os.path.join(base_dir, f))
                    logging.debug(f"Found GCP binding: {f}")
                    if test_mode:
                        break

    return files


def process_policies(
    quacky_path: str,
    aws_policies_dir: str = None,
    azure_role_def: str = None,
    azure_assignments_dir: str = None,
    gcp_roles: str = None,
    gcp_bindings_dir: str = None,
    bound: int = 250,
    output_csv: str = None,
    anthropic_api_key: str = None,
    test_mode: bool = False
) -> list:
    """
    Process all policies and generate results using the REGEX-BASED approach.

    Args:
        test_mode: If True, only process one policy from each cloud provider
    """
    results = []

    if test_mode:
        logging.info("=" * 60)
        logging.info("RUNNING IN TEST MODE - Processing only one policy per cloud")
        logging.info("=" * 60)

    # Resolve quacky_path to absolute so relative paths don't break when subprocess changes cwd
    quacky_path = os.path.abspath(quacky_path)

    # Initialize Anthropic client
    api_key = anthropic_api_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        logging.error("Anthropic API key is required. Set ANTHROPIC_API_KEY or use --api-key")
        return []

    if not HAS_ANTHROPIC:
        logging.error("anthropic package not installed. Run: pip install anthropic")
        return []

    client = anthropic.Anthropic(api_key=api_key)
    logging.info("Initialized Anthropic client for regex summarization")

    # Create temp directory for LLM regex files
    temp_dir = tempfile.mkdtemp(prefix='regex_summarizer_regex_based_')
    logging.info(f"Using temp directory: {temp_dir}")

    # Determine output paths - separate files for Azure and GCP
    os.makedirs('results', exist_ok=True)

    if output_csv:
        # User specified output path
        aws_output_csv = output_csv
        aws_json_path = output_csv.rsplit('.', 1)[0] + '.json'
        azure_output_csv = output_csv
        azure_json_path = output_csv.rsplit('.', 1)[0] + '.json'
        gcp_output_csv = output_csv
        gcp_json_path = output_csv.rsplit('.', 1)[0] + '.json'
    else:
        # Auto-generate separate paths for AWS, Azure and GCP
        aws_output_csv = 'results/results_aws_regex_based.csv'
        aws_json_path = 'results/results_aws_regex_based.json'
        azure_output_csv = 'results/results_azure_regex_based.csv'
        azure_json_path = 'results/results_azure_regex_based.json'
        gcp_output_csv = 'results/results_gcp_regex_based.csv'
        gcp_json_path = 'results/results_gcp_regex_based.json'

    # Separate results for AWS, Azure and GCP
    aws_results = []
    azure_results = []
    gcp_results = []
    aws_processed_files = set()
    azure_processed_files = set()
    gcp_processed_files = set()

    # Load existing AWS results if file exists (for resuming)
    if aws_policies_dir and os.path.exists(aws_json_path):
        logging.info(f"Found existing AWS results file: {aws_json_path}")
        try:
            with open(aws_json_path, 'r') as f:
                aws_results = json.load(f)
            aws_processed_files = {r['file'] for r in aws_results}
            logging.info(f"Loaded {len(aws_results)} existing AWS results. Will skip already processed files.")
        except Exception as e:
            logging.warning(f"Could not load existing AWS results: {e}. Starting fresh.")
            aws_results = []

    # Load existing Azure results if file exists (for resuming)
    if azure_role_def and azure_assignments_dir and os.path.exists(azure_json_path):
        logging.info(f"Found existing Azure results file: {azure_json_path}")
        try:
            with open(azure_json_path, 'r') as f:
                azure_results = json.load(f)
            azure_processed_files = {r['file'] for r in azure_results}
            logging.info(f"Loaded {len(azure_results)} existing Azure results. Will skip already processed files.")
        except Exception as e:
            logging.warning(f"Could not load existing Azure results: {e}. Starting fresh.")
            azure_results = []

    # Load existing GCP results if file exists (for resuming)
    if gcp_roles and gcp_bindings_dir and os.path.exists(gcp_json_path):
        logging.info(f"Found existing GCP results file: {gcp_json_path}")
        try:
            with open(gcp_json_path, 'r') as f:
                gcp_results = json.load(f)
            gcp_processed_files = {r['file'] for r in gcp_results}
            logging.info(f"Loaded {len(gcp_results)} existing GCP results. Will skip already processed files.")
        except Exception as e:
            logging.warning(f"Could not load existing GCP results: {e}. Starting fresh.")
            gcp_results = []

    # Process AWS policies
    if aws_policies_dir:
        logging.info("")
        logging.info("=" * 60)
        logging.info("Processing AWS Policies (Regex-Based Approach)")
        logging.info("=" * 60)

        policy_files = find_policy_files(aws_policies_dir, 'aws', max_files=600, test_mode=test_mode)
        logging.info(f"Found {len(policy_files)} AWS policy file(s)")

        for idx, policy_file in enumerate(policy_files):
            filename = os.path.basename(policy_file)
            logging.info("")
            logging.info(f"[{idx+1}/{len(policy_files)}] Processing: {filename}")

            # Skip if already processed
            if filename in aws_processed_files:
                logging.info(f"  SKIPPING: Already processed")
                continue

            # Step 1: Run Quacky to extract regex_from_dfa
            logging.info("  Step 1: Extracting regex from DFA...")
            extract_result = run_quacky_aws_extract(quacky_path, policy_file, bound)

            if extract_result['satisfiability'] != 'sat' or not extract_result['regex_from_dfa']:
                logging.error(f"  STOPPING: No regex extracted from Quacky (satisfiability: {extract_result['satisfiability']})")
                logging.error(f"  Cannot proceed without regex_from_dfa for comparison.")
                logging.error(f"  Raw stdout: {extract_result.get('raw_stdout', 'N/A')[:500]}")
                logging.error(f"  Raw stderr: {extract_result.get('raw_stderr', 'N/A')[:500]}")
                aws_results.append({
                    'cloud': 'aws',
                    'file': os.path.basename(policy_file),
                    'approach': 'regex_based',
                    'satisfiability': extract_result['satisfiability'],
                    'regex_from_dfa': None,
                    'regex_from_llm': None,
                    'jaccard_similarity': None,
                    'error': 'No regex extracted - cannot compare'
                })
                # Save progress even for failed files
                write_results_csv(aws_results, aws_output_csv)
                write_results_json(aws_results, aws_json_path)
                logging.info(f"  Progress saved ({len(aws_results)} total AWS results)")
                continue

            regex_dfa = extract_result['regex_from_dfa']
            logging.info(f"  Regex DFA extracted (length: {len(regex_dfa)})")
            logging.debug(f"  Regex DFA: {regex_dfa[:200]}..." if len(regex_dfa) > 200 else f"  Regex DFA: {regex_dfa}")

            # Retry loop with max iterations
            max_iterations = 5
            retry_context = None
            final_result = None

            try:
                with open(policy_file) as _pf:
                    policy_content = _pf.read()
            except Exception:
                policy_content = None

            for iteration in range(max_iterations):
                logging.info(f"  Step 2: Prompting LLM for summarized regex (attempt {iteration + 1}/{max_iterations})...")

                try:
                    regex_llm = prompt_llm_for_summary(regex_dfa, client, retry_context, policy_content)
                    logging.info(f"  Regex LLM generated (length: {len(regex_llm)})")
                    logging.debug(f"  Regex LLM: {regex_llm}")
                except Exception as e:
                    logging.error(f"  LLM call failed: {e}")
                    aws_results.append({
                        'cloud': 'aws',
                        'file': os.path.basename(policy_file),
                        'approach': 'regex_based',
                        'satisfiability': extract_result['satisfiability'],
                        'regex_from_dfa': regex_dfa,
                        'regex_from_llm': None,
                        'jaccard_similarity': None,
                        'error': str(e)
                    })
                    write_results_csv(aws_results, aws_output_csv)
                    write_results_json(aws_results, aws_json_path)
                    logging.info(f"  Progress saved ({len(aws_results)} total AWS results)")
                    break

                # Validate regex syntax with grep -P before calling quacky
                if not is_valid_perl_regex(regex_llm):
                    logging.warning(f"  LLM regex has invalid syntax (grep -P rejected it), retrying...")
                    continue

                # Step 3: Write LLM regex to temp file
                llm_regex_file = os.path.join(temp_dir, f'llm_regex_aws_{idx}_iter{iteration}.txt')
                with open(llm_regex_file, 'w') as f:
                    f.write(regex_llm)
                logging.debug(f"  Wrote LLM regex to: {llm_regex_file}")

                # Step 4: Run Quacky with --compareregex to compute Jaccard similarity
                logging.info(f"  Step 3: Running Quacky --compareregex to compute Jaccard similarity...")
                compare_result = run_quacky_aws_compare(
                    quacky_path, policy_file, llm_regex_file, bound
                )

                final_result = {
                    'cloud': 'aws',
                    'file': os.path.basename(policy_file),
                    'approach': 'regex_based',
                    'solve_time_ms': compare_result['solve_time'],
                    'satisfiability': compare_result['satisfiability'],
                    'count_time_ms': compare_result['count_time'],
                    'lg_requests': compare_result['lg_requests'],
                    'regex_from_dfa': regex_dfa,
                    'regex_from_llm': regex_llm,
                    'baseline_regex_count': compare_result['baseline_regex_count'],
                    'synthesized_regex_count': compare_result['synthesized_regex_count'],
                    'jaccard_numerator': compare_result['jaccard_numerator'],
                    'jaccard_denominator': compare_result['jaccard_denominator'],
                    'jaccard_similarity': compare_result['jaccard_similarity'],
                    'ops_regex_from_dfa': compare_result['ops_regex_from_dfa'],
                    'ops_regex_from_llm': compare_result['ops_regex_from_llm'],
                    'length_regex_from_dfa': compare_result['length_regex_from_dfa'],
                    'length_regex_from_llm': compare_result['length_regex_from_llm'],
                    'iteration': iteration + 1
                }

                logging.info(f"  Results (iteration {iteration + 1}):")
                logging.info(f"    Jaccard Similarity: {compare_result['jaccard_similarity']}")
                logging.info(f"    Baseline (DFA) Count: {compare_result['baseline_regex_count']}")
                logging.info(f"    Synthesized (LLM) Count: {compare_result['synthesized_regex_count']}")
                logging.info(f"    DFA regex length: {compare_result['length_regex_from_dfa']}")
                logging.info(f"    LLM regex length: {compare_result['length_regex_from_llm']}")

                # Check if we need to retry
                jaccard_sim = compare_result['jaccard_similarity']
                try:
                    sim_value = float(jaccard_sim) if jaccard_sim is not None else 0.0
                except (ValueError, TypeError):
                    sim_value = 0.0

                if sim_value < 0.9:  # Retry if similarity is below 90%
                    if iteration < max_iterations - 1:
                        logging.warning(f"  Jaccard similarity is {jaccard_sim}, retrying with feedback...")
                        retry_context = {
                            'previous_regex': regex_llm,
                            'baseline_count': compare_result['baseline_regex_count'],
                            'synthesized_count': compare_result['synthesized_regex_count'],
                            'jaccard_similarity': jaccard_sim
                        }
                    else:
                        logging.warning(f"  Jaccard similarity is {jaccard_sim}, max iterations reached")
                        break
                else:
                    # Success! No need to retry
                    logging.info(f"  Success! Jaccard similarity is acceptable: {jaccard_sim}")
                    break

            if final_result:
                aws_results.append(final_result)

            # Save progress immediately after each file
            write_results_csv(aws_results, aws_output_csv)
            write_results_json(aws_results, aws_json_path)
            logging.info(f"  Progress saved ({len(aws_results)} total AWS results)")

    # Process Azure policies
    if azure_role_def and azure_assignments_dir:
        logging.info("")
        logging.info("=" * 60)
        logging.info("Processing Azure Policies (Regex-Based Approach)")
        logging.info("=" * 60)

        assignment_files = find_policy_files(azure_assignments_dir, 'azure', test_mode=test_mode)
        logging.info(f"Found {len(assignment_files)} Azure role assignment file(s)")

        for idx, assignment_file in enumerate(assignment_files):
            filename = os.path.basename(assignment_file)
            logging.info("")
            logging.info(f"[{idx+1}/{len(assignment_files)}] Processing: {filename}")

            # Skip if already processed
            if filename in azure_processed_files:
                logging.info(f"  SKIPPING: Already processed")
                continue

            # Step 1: Run Quacky to extract regex_from_dfa
            logging.info("  Step 1: Extracting regex from DFA...")
            extract_result = run_quacky_azure_extract(quacky_path, azure_role_def, assignment_file, bound)

            if extract_result['satisfiability'] != 'sat' or not extract_result['regex_from_dfa']:
                logging.error(f"  STOPPING: No regex extracted from Quacky (satisfiability: {extract_result['satisfiability']})")
                logging.error(f"  Cannot proceed without regex_from_dfa for comparison.")
                logging.error(f"  Raw stdout: {extract_result.get('raw_stdout', 'N/A')[:500]}")
                logging.error(f"  Raw stderr: {extract_result.get('raw_stderr', 'N/A')[:500]}")
                azure_results.append({
                    'cloud': 'azure',
                    'file': os.path.basename(assignment_file),
                    'approach': 'regex_based',
                    'satisfiability': extract_result['satisfiability'],
                    'regex_from_dfa': None,
                    'regex_from_llm': None,
                    'jaccard_similarity': None,
                    'error': 'No regex extracted - cannot compare'
                })
                # Save progress even for failed files
                write_results_csv(azure_results, azure_output_csv)
                write_results_json(azure_results, azure_json_path)
                logging.info(f"  Progress saved ({len(azure_results)} total Azure results)")
                continue

            regex_dfa = extract_result['regex_from_dfa']
            logging.info(f"  Regex DFA extracted (length: {len(regex_dfa)})")
            logging.debug(f"  Regex DFA: {regex_dfa[:200]}..." if len(regex_dfa) > 200 else f"  Regex DFA: {regex_dfa}")

            try:
                with open(policy_file) as _pf:
                    policy_content = _pf.read()
            except Exception:
                policy_content = None

            # Retry loop with max iterations
            max_iterations = 5
            retry_context = None
            final_result = None

            for iteration in range(max_iterations):
                logging.info(f"  Step 2: Prompting LLM for summarized regex (attempt {iteration + 1}/{max_iterations})...")

                try:
                    regex_llm = prompt_llm_for_summary(regex_dfa, client, retry_context, policy_content)
                    logging.info(f"  Regex LLM generated (length: {len(regex_llm)})")
                    logging.debug(f"  Regex LLM: {regex_llm}")
                except Exception as e:
                    logging.error(f"  LLM call failed: {e}")
                    azure_results.append({
                        'cloud': 'azure',
                        'file': os.path.basename(assignment_file),
                        'approach': 'regex_based',
                        'satisfiability': extract_result['satisfiability'],
                        'regex_from_dfa': regex_dfa,
                        'regex_from_llm': None,
                        'jaccard_similarity': None,
                        'error': str(e)
                    })
                    write_results_csv(azure_results, azure_output_csv)
                    write_results_json(azure_results, azure_json_path)
                    logging.info(f"  Progress saved ({len(azure_results)} total Azure results)")
                    break

                # Validate regex syntax with grep -P before calling quacky
                if not is_valid_perl_regex(regex_llm):
                    logging.warning(f"  LLM regex has invalid syntax (grep -P rejected it), retrying...")
                    continue

                # Step 3: Write LLM regex to temp file
                llm_regex_file = os.path.join(temp_dir, f'llm_regex_azure_{idx}_iter{iteration}.txt')
                with open(llm_regex_file, 'w') as f:
                    f.write(regex_llm)
                logging.debug(f"  Wrote LLM regex to: {llm_regex_file}")

                # Step 4: Run Quacky with --compareregex to compute Jaccard similarity
                logging.info(f"  Step 3: Running Quacky --compareregex to compute Jaccard similarity...")
                compare_result = run_quacky_azure_compare(
                    quacky_path, azure_role_def, assignment_file, llm_regex_file, bound
                )

                final_result = {
                    'cloud': 'azure',
                    'file': os.path.basename(assignment_file),
                    'approach': 'regex_based',
                    'solve_time_ms': compare_result['solve_time'],
                    'satisfiability': compare_result['satisfiability'],
                    'count_time_ms': compare_result['count_time'],
                    'lg_requests': compare_result['lg_requests'],
                    'regex_from_dfa': regex_dfa,
                    'regex_from_llm': regex_llm,
                    'baseline_regex_count': compare_result['baseline_regex_count'],
                    'synthesized_regex_count': compare_result['synthesized_regex_count'],
                    'jaccard_numerator': compare_result['jaccard_numerator'],
                    'jaccard_denominator': compare_result['jaccard_denominator'],
                    'jaccard_similarity': compare_result['jaccard_similarity'],
                    'ops_regex_from_dfa': compare_result['ops_regex_from_dfa'],
                    'ops_regex_from_llm': compare_result['ops_regex_from_llm'],
                    'length_regex_from_dfa': compare_result['length_regex_from_dfa'],
                    'length_regex_from_llm': compare_result['length_regex_from_llm'],
                    'iteration': iteration + 1
                }

                logging.info(f"  Results (iteration {iteration + 1}):")
                logging.info(f"    Jaccard Similarity: {compare_result['jaccard_similarity']}")
                logging.info(f"    Baseline (DFA) Count: {compare_result['baseline_regex_count']}")
                logging.info(f"    Synthesized (LLM) Count: {compare_result['synthesized_regex_count']}")
                logging.info(f"    DFA regex length: {compare_result['length_regex_from_dfa']}")
                logging.info(f"    LLM regex length: {compare_result['length_regex_from_llm']}")

                # Check if we need to retry
                jaccard_sim = compare_result['jaccard_similarity']
                try:
                    sim_value = float(jaccard_sim) if jaccard_sim is not None else 0.0
                except (ValueError, TypeError):
                    sim_value = 0.0

                if sim_value < 0.9:  # Retry if similarity is below 90%
                    if iteration < max_iterations - 1:
                        logging.warning(f"  Jaccard similarity is {jaccard_sim}, retrying with feedback...")
                        retry_context = {
                            'previous_regex': regex_llm,
                            'baseline_count': compare_result['baseline_regex_count'],
                            'synthesized_count': compare_result['synthesized_regex_count'],
                            'jaccard_similarity': jaccard_sim
                        }
                    else:
                        logging.warning(f"  Jaccard similarity is {jaccard_sim}, max iterations reached")
                        break
                else:
                
                    logging.info(f"  Success! Jaccard similarity is acceptable: {jaccard_sim}")
                    break

            if final_result:
                azure_results.append(final_result)

            # Save progress immediately after each file
            write_results_csv(azure_results, azure_output_csv)
            write_results_json(azure_results, azure_json_path)
            logging.info(f"  Progress saved ({len(azure_results)} total Azure results)")

    # Process GCP policies
    if gcp_roles and gcp_bindings_dir:
        logging.info("")
        logging.info("=" * 60)
        logging.info("Processing GCP Policies (Regex-Based Approach)")
        logging.info("=" * 60)

        binding_files = find_policy_files(gcp_bindings_dir, 'gcp', test_mode=test_mode)
        logging.info(f"Found {len(binding_files)} GCP role binding file(s)")

        for idx, binding_file in enumerate(binding_files):
            filename = os.path.basename(binding_file)
            logging.info("")
            logging.info(f"[{idx+1}/{len(binding_files)}] Processing: {filename}")

            # Skip if already processed
            if filename in gcp_processed_files:
                logging.info(f"  SKIPPING: Already processed")
                continue

            # Step 1: Run Quacky to extract regex_from_dfa
            logging.info("  Step 1: Extracting regex from DFA...")
            extract_result = run_quacky_gcp_extract(quacky_path, gcp_roles, binding_file, bound)

            if extract_result['satisfiability'] != 'sat' or not extract_result['regex_from_dfa']:
                logging.error(f"  STOPPING: No regex extracted from Quacky (satisfiability: {extract_result['satisfiability']})")
                logging.error(f"  Cannot proceed without regex_from_dfa for comparison.")
                logging.error(f"  Raw stdout: {extract_result.get('raw_stdout', 'N/A')[:500]}")
                logging.error(f"  Raw stderr: {extract_result.get('raw_stderr', 'N/A')[:500]}")
                gcp_results.append({
                    'cloud': 'gcp',
                    'file': os.path.basename(binding_file),
                    'approach': 'regex_based',
                    'satisfiability': extract_result['satisfiability'],
                    'regex_from_dfa': None,
                    'regex_from_llm': None,
                    'jaccard_similarity': None,
                    'error': 'No regex extracted - cannot compare'
                })
                write_results_csv(gcp_results, gcp_output_csv)
                write_results_json(gcp_results, gcp_json_path)
                logging.info(f"  Progress saved ({len(gcp_results)} total GCP results)")
                continue

            regex_dfa = extract_result['regex_from_dfa']
            logging.info(f"  Regex DFA extracted (length: {len(regex_dfa)})")
            logging.debug(f"  Regex DFA: {regex_dfa[:200]}..." if len(regex_dfa) > 200 else f"  Regex DFA: {regex_dfa}")

            try:
                with open(policy_file) as _pf:
                    policy_content = _pf.read()
            except Exception:
                policy_content = None

            # Retry loop with max iterations
            max_iterations = 5
            retry_context = None
            final_result = None

            for iteration in range(max_iterations):
                logging.info(f"  Step 2: Prompting LLM for summarized regex (attempt {iteration + 1}/{max_iterations})...")

                try:
                    regex_llm = prompt_llm_for_summary(regex_dfa, client, retry_context, policy_content)
                    logging.info(f"  Regex LLM generated (length: {len(regex_llm)})")
                    logging.debug(f"  Regex LLM: {regex_llm}")
                except Exception as e:
                    logging.error(f"  LLM call failed: {e}")
                    gcp_results.append({
                        'cloud': 'gcp',
                        'file': os.path.basename(binding_file),
                        'approach': 'regex_based',
                        'satisfiability': extract_result['satisfiability'],
                        'regex_from_dfa': regex_dfa,
                        'regex_from_llm': None,
                        'jaccard_similarity': None,
                        'error': str(e)
                    })
                    write_results_csv(gcp_results, gcp_output_csv)
                    write_results_json(gcp_results, gcp_json_path)
                    logging.info(f"  Progress saved ({len(gcp_results)} total GCP results)")
                    break

                # Validate regex syntax with grep -P before calling quacky
                if not is_valid_perl_regex(regex_llm):
                    logging.warning(f"  LLM regex has invalid syntax (grep -P rejected it), retrying...")
                    continue

                # Step 3: Write LLM regex to temp file
                llm_regex_file = os.path.join(temp_dir, f'llm_regex_gcp_{idx}_iter{iteration}.txt')
                with open(llm_regex_file, 'w') as f:
                    f.write(regex_llm)
                logging.debug(f"  Wrote LLM regex to: {llm_regex_file}")

                # Step 4: Run Quacky with --compareregex to compute Jaccard similarity
                logging.info(f"  Step 3: Running Quacky --compareregex to compute Jaccard similarity...")
                compare_result = run_quacky_gcp_compare(
                    quacky_path, gcp_roles, binding_file, llm_regex_file, bound
                )

                final_result = {
                    'cloud': 'gcp',
                    'file': os.path.basename(binding_file),
                    'approach': 'regex_based',
                    'solve_time_ms': compare_result['solve_time'],
                    'satisfiability': compare_result['satisfiability'],
                    'count_time_ms': compare_result['count_time'],
                    'lg_requests': compare_result['lg_requests'],
                    'regex_from_dfa': regex_dfa,
                    'regex_from_llm': regex_llm,
                    'baseline_regex_count': compare_result['baseline_regex_count'],
                    'synthesized_regex_count': compare_result['synthesized_regex_count'],
                    'jaccard_numerator': compare_result['jaccard_numerator'],
                    'jaccard_denominator': compare_result['jaccard_denominator'],
                    'jaccard_similarity': compare_result['jaccard_similarity'],
                    'ops_regex_from_dfa': compare_result['ops_regex_from_dfa'],
                    'ops_regex_from_llm': compare_result['ops_regex_from_llm'],
                    'length_regex_from_dfa': compare_result['length_regex_from_dfa'],
                    'length_regex_from_llm': compare_result['length_regex_from_llm'],
                    'iteration': iteration + 1
                }

                logging.info(f"  Results (iteration {iteration + 1}):")
                logging.info(f"    Jaccard Similarity: {compare_result['jaccard_similarity']}")
                logging.info(f"    Baseline (DFA) Count: {compare_result['baseline_regex_count']}")
                logging.info(f"    Synthesized (LLM) Count: {compare_result['synthesized_regex_count']}")
                logging.info(f"    DFA regex length: {compare_result['length_regex_from_dfa']}")
                logging.info(f"    LLM regex length: {compare_result['length_regex_from_llm']}")

                # Check if we need to retry
                jaccard_sim = compare_result['jaccard_similarity']
                try:
                    sim_value = float(jaccard_sim) if jaccard_sim is not None else 0.0
                except (ValueError, TypeError):
                    sim_value = 0.0

                if sim_value < 0.9:  # Retry if similarity is below 90%
                    if iteration < max_iterations - 1:
                        logging.warning(f"  Jaccard similarity is {jaccard_sim}, retrying with feedback...")
                        retry_context = {
                            'previous_regex': regex_llm,
                            'baseline_count': compare_result['baseline_regex_count'],
                            'synthesized_count': compare_result['synthesized_regex_count'],
                            'jaccard_similarity': jaccard_sim
                        }
                    else:
                        logging.warning(f"  Jaccard similarity is {jaccard_sim}, max iterations reached")
                        break
                else:
                    # Success! No need to retry
                    logging.info(f"  Success! Jaccard similarity is acceptable: {jaccard_sim}")
                    break

            if final_result:
                gcp_results.append(final_result)

            write_results_csv(gcp_results, gcp_output_csv)
            write_results_json(gcp_results, gcp_json_path)
            logging.info(f"  Progress saved ({len(gcp_results)} total GCP results)")

    # Final save and summary
    all_results = aws_results + azure_results + gcp_results

    if aws_results:
        logging.info(f"\nFinal save: {len(aws_results)} AWS results")
        write_results_csv(aws_results, aws_output_csv)
        write_results_json(aws_results, aws_json_path)
        logging.info(f"  AWS CSV: {aws_output_csv}")
        logging.info(f"  AWS JSON: {aws_json_path}")

    if azure_results:
        logging.info(f"\nFinal save: {len(azure_results)} Azure results")
        write_results_csv(azure_results, azure_output_csv)
        write_results_json(azure_results, azure_json_path)
        logging.info(f"  Azure CSV: {azure_output_csv}")
        logging.info(f"  Azure JSON: {azure_json_path}")

    if gcp_results:
        logging.info(f"\nFinal save: {len(gcp_results)} GCP results")
        write_results_csv(gcp_results, gcp_output_csv)
        write_results_json(gcp_results, gcp_json_path)
        logging.info(f"  GCP CSV: {gcp_output_csv}")
        logging.info(f"  GCP JSON: {gcp_json_path}")

    print_summary(all_results)


    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    logging.debug(f"Cleaned up temp directory: {temp_dir}")

    return all_results


def write_results_csv(results: list, output_path: str):
    """Write results to a CSV file."""
    if not results:
        return

    fieldnames = [
        'cloud', 'file', 'approach', 'iteration',
        'solve_time_ms', 'satisfiability', 'count_time_ms',
        'lg_requests', 'jaccard_similarity', 'jaccard_numerator', 'jaccard_denominator',
        'baseline_regex_count', 'synthesized_regex_count',
        'ops_regex_from_dfa', 'ops_regex_from_llm',
        'length_regex_from_dfa', 'length_regex_from_llm',
        'regex_from_dfa', 'regex_from_llm'
    ]

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)

    logging.info(f"Results written to CSV: {output_path}")


def write_results_json(results: list, output_path: str):
    """Write results to a JSON file."""
    if not results:
        return

    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    logging.info(f"Results written to JSON: {output_path}")


def print_summary(results: list):
    """Print a summary of all results."""
    if not results:
        logging.info("No results to summarize.")
        return

    logging.info("")
    logging.info("=" * 60)
    logging.info("SUMMARY (Regex-Based Approach)")
    logging.info("=" * 60)

    # Filter results with valid similarities
    valid_results = [r for r in results if r.get('jaccard_similarity') is not None]

    if not valid_results:
        logging.info("No valid results with Jaccard similarity computed.")
        return

    logging.info(f"Total results: {len(results)}")
    logging.info(f"Valid results with Jaccard similarity: {len(valid_results)}")
    logging.info("")

    # Overall stats
    jaccard_values = []
    for r in valid_results:
        try:
            jaccard_values.append(float(r['jaccard_similarity']))
        except (ValueError, TypeError):
            pass

    if jaccard_values:
        avg_jaccard = sum(jaccard_values) / len(jaccard_values)
        min_jaccard = min(jaccard_values)
        max_jaccard = max(jaccard_values)

        logging.info(f"Overall Jaccard Similarity:")
        logging.info(f"  Average: {avg_jaccard:.4f}")
        logging.info(f"  Min: {min_jaccard:.4f}")
        logging.info(f"  Max: {max_jaccard:.4f}")

    # Per-cloud stats
    for cloud in ['aws', 'azure', 'gcp']:
        cloud_results = [r for r in valid_results if r['cloud'] == cloud]
        if cloud_results:
            cloud_jaccard = []
            for r in cloud_results:
                try:
                    cloud_jaccard.append(float(r['jaccard_similarity']))
                except (ValueError, TypeError):
                    pass

            if cloud_jaccard:
                logging.info(f"")
                logging.info(f"{cloud.upper()}:")
                logging.info(f"  Policies: {len(cloud_results)}")
                logging.info(f"  Avg Jaccard: {sum(cloud_jaccard)/len(cloud_jaccard):.4f}")
                logging.info(f"  Min Jaccard: {min(cloud_jaccard):.4f}")
                logging.info(f"  Max Jaccard: {max(cloud_jaccard):.4f}")

    logging.info("")


def main():
    parser = argparse.ArgumentParser(
        description='Process cloud policies using REGEX-BASED approach: extract regex via Quacky, summarize with LLM, compute Jaccard similarity',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # AWS example
  python3 regex_summarizer_regex_based.py -q /path/to/quacky.py -apd ./aws/

  # AWS test mode (auto-saves to results/ folder)
  python3 regex_summarizer_regex_based.py --test -q /path/to/quacky.py -apd ./aws/

  # Azure test mode
  python3 regex_summarizer_regex_based.py --test -q /path/to/quacky.py -ard role_def.json -aad ./assignments/

  # Full run with custom output path
  python3 regex_summarizer_regex_based.py -q /path/to/quacky.py -ard role_def.json -aad ./assignments/ -o results/output.csv --log run.log

  # GCP example
  python3 regex_summarizer_regex_based.py -q /path/to/quacky.py -gr combined_roles.json -gbd ./bindings/

  # Verbose mode for debugging
  python3 regex_summarizer_regex_based.py --test -v -q /path/to/quacky.py -apd ./aws/
        """
    )


    parser.add_argument(
        '--quacky', '-q',
        required=True,
        help='Path to quacky.py'
    )


    parser.add_argument(
        '--aws-policies-dir', '-apd',
        help='Directory containing AWS policy files (aws0.json - aws586.json)'
    )

    parser.add_argument(
        '--azure-role-def', '-ard',
        help='Path to Azure role definitions JSON file'
    )
    parser.add_argument(
        '--azure-assignments-dir', '-aad',
        help='Directory containing Azure role assignments (as0.json - as100.json)'
    )


    parser.add_argument(
        '--gcp-roles', '-gr',
        help='Path to GCP roles JSON file'
    )
    parser.add_argument(
        '--gcp-bindings-dir', '-gbd',
        help='Directory containing GCP role bindings (bd0.json - bd100.json)'
    )


    parser.add_argument(
        '--bound', '-b',
        type=int,
        default=250,
        help='Bound parameter for Quacky (default: 250)'
    )
    parser.add_argument(
        '--output', '-o',
        help='Output file path (saves both .csv and .json formats). If not specified, saves to results/ folder.'
    )
    parser.add_argument(
        '--api-key',
        help='Anthropic API key (or set ANTHROPIC_API_KEY env var)'
    )


    parser.add_argument(
        '--test', '-t',
        action='store_true',
        help='Test mode: process only one policy from each cloud provider'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output (show debug messages)'
    )
    parser.add_argument(
        '--log',
        help='Log file path (logs everything to this file)'
    )

    args = parser.parse_args()


    log_file = args.log
    if args.test and not log_file:

        log_file = f"test_run_regex_based_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    setup_logging(log_file=log_file, verbose=args.verbose)

    logging.info("=" * 60)
    logging.info("Regex Summarizer for Cloud Policies (REGEX-BASED APPROACH)")
    logging.info("=" * 60)
    logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Test mode: {args.test}")
    logging.info(f"Verbose: {args.verbose}")
    logging.info(f"Quacky path: {args.quacky}")
    if args.aws_policies_dir:
        logging.info(f"AWS policies dir: {args.aws_policies_dir}")
    if args.azure_role_def:
        logging.info(f"Azure role definitions: {args.azure_role_def}")
        logging.info(f"Azure assignments dir: {args.azure_assignments_dir}")
    if args.gcp_roles:
        logging.info(f"GCP roles: {args.gcp_roles}")
        logging.info(f"GCP bindings dir: {args.gcp_bindings_dir}")
    logging.info(f"Bound: {args.bound}")
    if args.output:
        json_output = args.output.rsplit('.', 1)[0] + '.json'
        logging.info(f"Output files: {args.output} and {json_output}")
    else:
        logging.info(f"Output: Will save to results/ folder")

    # Validate arguments
    if not args.aws_policies_dir and not args.azure_role_def and not args.gcp_roles:
        parser.error("At least one of --aws-policies-dir, --azure-role-def, or --gcp-roles must be provided")

    if args.azure_role_def and not args.azure_assignments_dir:
        parser.error("--azure-assignments-dir is required when --azure-role-def is provided")

    if args.gcp_roles and not args.gcp_bindings_dir:
        parser.error("--gcp-bindings-dir is required when --gcp-roles is provided")


    results = process_policies(
        quacky_path=args.quacky,
        aws_policies_dir=args.aws_policies_dir,
        azure_role_def=args.azure_role_def,
        azure_assignments_dir=args.azure_assignments_dir,
        gcp_roles=args.gcp_roles,
        gcp_bindings_dir=args.gcp_bindings_dir,
        bound=args.bound,
        output_csv=args.output,
        anthropic_api_key=args.api_key,
        test_mode=args.test
    )

    logging.info("")
    logging.info(f"Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if log_file:
        logging.info(f"Full log saved to: {log_file}")

    return results


if __name__ == '__main__':
    main()
