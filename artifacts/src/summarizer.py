#!/usr/bin/env python3
"""
Regex Summarizer for Cloud Policies

This script:
1. Processes Azure role definitions/assignments and GCP roles/bindings
2. Runs Quacky to extract regex from DFA (regex_from_dfa)
3. Prompts an LLM to generate a summarized equivalent regex
4. Writes the LLM regex to a file
5. Runs Quacky again with --compareregex to compute Jaccard similarity using ABC

Usage:
    # Test mode (one policy each)
    python3 regex_summarizer.py --test -q /path/to/quacky.py -ard role_def.json -aad ./assignments/ -gr roles.json -gbd ./bindings/
    
    # Full run
    python3 regex_summarizer.py -q /path/to/quacky.py -ard role_def.json -aad ./assignments/ -o results.csv
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

#!/usr/bin/env python3
"""
Regex Summarizer for Cloud Policies

This script:
1. Processes Azure role definitions/assignments and GCP roles/bindings
2. Runs Quacky to extract regex from DFA (regex_from_dfa)
3. Prompts an LLM to generate a summarized equivalent regex
4. Writes the LLM regex to a file
5. Runs Quacky again with --compareregex to compute Jaccard similarity using ABC

Usage:
    # Test mode (one policy each)
    python3 regex_summarizer.py --test -q /path/to/quacky.py -ard role_def.json -aad ./assignments/ -gr roles.json -gbd ./bindings/
    
    # Full run
    python3 regex_summarizer.py -q /path/to/quacky.py -ard role_def.json -aad ./assignments/ -o results.csv
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

# Try to import anthropic for LLM calls
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
    
    # File handler (if specified)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logging.info(f"Logging to file: {log_file}")
    
    return logger


def run_quacky_azure_extract(quacky_path: str, role_def: str, role_assignment: str, bound: int = 150) -> dict:
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


def run_quacky_gcp_extract(quacky_path: str, roles: str, role_binding: str, bound: int = 150) -> dict:
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
                              llm_regex_file: str, bound: int = 150) -> dict:
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
                           llm_regex_file: str, bound: int = 150) -> dict:
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
        'baseline_not_synthesized': None,
        'not_baseline_synthesized': None,
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
            # Could be "regex_from_dfa:" or "regex_from_dfa                :"
            val = line.split(':', 1)[1].strip()
            result['regex_from_dfa'] = val
        elif line.startswith('regex_from_llm'):
            val = line.split(':', 1)[1].strip()
            result['regex_from_llm'] = val
        elif line.startswith('Baseline Regex Count'):
            result['baseline_regex_count'] = line.split(':', 1)[1].strip()
        elif line.startswith('Synthesized Regex Count'):
            result['synthesized_regex_count'] = line.split(':', 1)[1].strip()
        elif line.startswith('Baseline_Not_Synthesized Count'):
            result['baseline_not_synthesized'] = line.split(':', 1)[1].strip()
        elif line.startswith('Not_Baseline_Synthesized_Count'):
            result['not_baseline_synthesized'] = line.split(':', 1)[1].strip()
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


def prompt_llm_for_summary(regex: str, client) -> str:
    """
    Prompt an LLM to generate a summarized equivalent regex.
    
    Args:
        regex: The original regex from DFA
        client: Anthropic client
        
    Returns:
        Summarized regex from LLM
    """
    prompt = f"""You are an expert in regular expressions and cloud security policies.

Given the following regex extracted from a DFA representing cloud resource access patterns:

{regex}

Please generate a SIMPLIFIED, human-readable equivalent regex that captures the same semantic meaning.

Rules:
1. The simplified regex should be shorter and more readable
2. Use common regex shorthand like .* for "any characters", [a-zA-Z0-9] for alphanumeric, etc.
3. Preserve the essential structure (e.g., subscription IDs, resource group patterns, paths)
4. Replace long character classes with simpler equivalents where appropriate
5. The regex should still match the same general pattern of resources
6. Keep important literal strings like subscription IDs, resource group names, etc.

IMPORTANT: Respond with ONLY the simplified regex on a single line. No explanation, no markdown, no backticks, no other text."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return message.content[0].text.strip()


def find_policy_files(base_dir: str, cloud_type: str, max_files: int = 51, test_mode: bool = False) -> list:
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
    
    if cloud_type == 'azure':
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
    azure_role_def: str = None,
    azure_assignments_dir: str = None,
    gcp_roles: str = None,
    gcp_bindings_dir: str = None,
    bound: int = 150,
    output_csv: str = None,
    anthropic_api_key: str = None,
    test_mode: bool = False
) -> list:
    """
    Process all policies and generate results.
    
    Args:
        test_mode: If True, only process one policy from each cloud provider
    """
    results = []
    
    if test_mode:
        logging.info("=" * 60)
        logging.info("RUNNING IN TEST MODE - Processing only one policy per cloud")
        logging.info("=" * 60)
    
    # Initialize Anthropic client
    api_key = anthropic_api_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        logging.error("Anthropic API key is required. Set ANTHROPIC_API_KEY or use --api-key")
        return results
    
    if not HAS_ANTHROPIC:
        logging.error("anthropic package not installed. Run: pip install anthropic")
        return results
    
    client = anthropic.Anthropic(api_key=api_key)
    logging.info("Initialized Anthropic client for regex summarization")
    
    # Create temp directory for LLM regex files
    temp_dir = tempfile.mkdtemp(prefix='regex_summarizer_')
    logging.info(f"Using temp directory: {temp_dir}")
    
    # Process Azure policies
    if azure_role_def and azure_assignments_dir:
        logging.info("")
        logging.info("=" * 60)
        logging.info("Processing Azure Policies")
        logging.info("=" * 60)
        
        assignment_files = find_policy_files(azure_assignments_dir, 'azure', test_mode=test_mode)
        logging.info(f"Found {len(assignment_files)} Azure role assignment file(s)")
        
        for idx, assignment_file in enumerate(assignment_files):
            logging.info("")
            logging.info(f"[{idx+1}/{len(assignment_files)}] Processing: {os.path.basename(assignment_file)}")
            
            # Step 1: Run Quacky to extract regex_from_dfa
            logging.info("  Step 1: Extracting regex from DFA...")
            extract_result = run_quacky_azure_extract(quacky_path, azure_role_def, assignment_file, bound)
            
            if extract_result['satisfiability'] != 'sat' or not extract_result['regex_from_dfa']:
                logging.error(f"  STOPPING: No regex extracted from Quacky (satisfiability: {extract_result['satisfiability']})")
                logging.error(f"  Cannot proceed without regex_from_dfa for comparison.")
                logging.error(f"  Raw stdout: {extract_result.get('raw_stdout', 'N/A')[:500]}")
                logging.error(f"  Raw stderr: {extract_result.get('raw_stderr', 'N/A')[:500]}")
                results.append({
                    'cloud': 'azure',
                    'file': os.path.basename(assignment_file),
                    'satisfiability': extract_result['satisfiability'],
                    'regex_from_dfa': None,
                    'regex_from_llm': None,
                    'jaccard_similarity': None,
                    'error': 'No regex extracted - cannot compare'
                })
                # Stop processing this file, but continue to next file
                continue
            
            regex_dfa = extract_result['regex_from_dfa']
            logging.info(f"  Regex DFA extracted (length: {len(regex_dfa)})")
            logging.debug(f"  Regex DFA: {regex_dfa[:200]}..." if len(regex_dfa) > 200 else f"  Regex DFA: {regex_dfa}")
            
            # Step 2: Prompt LLM to summarize the regex
            logging.info("  Step 2: Prompting LLM for summarized regex...")
            try:
                regex_llm = prompt_llm_for_summary(regex_dfa, client)
                logging.info(f"  Regex LLM generated (length: {len(regex_llm)})")
                logging.debug(f"  Regex LLM: {regex_llm}")
            except Exception as e:
                logging.error(f"  LLM call failed: {e}")
                results.append({
                    'cloud': 'azure',
                    'file': os.path.basename(assignment_file),
                    'satisfiability': extract_result['satisfiability'],
                    'regex_from_dfa': regex_dfa,
                    'regex_from_llm': None,
                    'jaccard_similarity': None,
                    'error': str(e)
                })
                continue
            
            # Step 3: Write LLM regex to temp file
            llm_regex_file = os.path.join(temp_dir, f'llm_regex_azure_{idx}.txt')
            with open(llm_regex_file, 'w') as f:
                f.write(regex_llm)
            logging.debug(f"  Wrote LLM regex to: {llm_regex_file}")
            
            # Step 4: Run Quacky with --compareregex to compute Jaccard similarity
            logging.info("  Step 3: Running Quacky --compareregex to compute Jaccard similarity...")
            compare_result = run_quacky_azure_compare(
                quacky_path, azure_role_def, assignment_file, llm_regex_file, bound
            )
            
            result = {
                'cloud': 'azure',
                'file': os.path.basename(assignment_file),
                'solve_time_ms': compare_result['solve_time'],
                'satisfiability': compare_result['satisfiability'],
                'count_time_ms': compare_result['count_time'],
                'lg_requests': compare_result['lg_requests'],
                'regex_from_dfa': regex_dfa,
                'regex_from_llm': regex_llm,
                'baseline_regex_count': compare_result['baseline_regex_count'],
                'synthesized_regex_count': compare_result['synthesized_regex_count'],
                'baseline_not_synthesized': compare_result['baseline_not_synthesized'],
                'not_baseline_synthesized': compare_result['not_baseline_synthesized'],
                'jaccard_numerator': compare_result['jaccard_numerator'],
                'jaccard_denominator': compare_result['jaccard_denominator'],
                'jaccard_similarity': compare_result['jaccard_similarity'],
                'ops_regex_from_dfa': compare_result['ops_regex_from_dfa'],
                'ops_regex_from_llm': compare_result['ops_regex_from_llm'],
                'length_regex_from_dfa': compare_result['length_regex_from_dfa'],
                'length_regex_from_llm': compare_result['length_regex_from_llm'],
            }
            
            logging.info(f"  Results:")
            logging.info(f"    Jaccard Similarity: {compare_result['jaccard_similarity']}")
            logging.info(f"    Baseline (DFA) Count: {compare_result['baseline_regex_count']}")
            logging.info(f"    Synthesized (LLM) Count: {compare_result['synthesized_regex_count']}")
            logging.info(f"    DFA regex length: {compare_result['length_regex_from_dfa']}")
            logging.info(f"    LLM regex length: {compare_result['length_regex_from_llm']}")
            
            results.append(result)
    
    # Process GCP policies
    if gcp_roles and gcp_bindings_dir:
        logging.info("")
        logging.info("=" * 60)
        logging.info("Processing GCP Policies")
        logging.info("=" * 60)
        
        binding_files = find_policy_files(gcp_bindings_dir, 'gcp', test_mode=test_mode)
        logging.info(f"Found {len(binding_files)} GCP role binding file(s)")
        
        for idx, binding_file in enumerate(binding_files):
            logging.info("")
            logging.info(f"[{idx+1}/{len(binding_files)}] Processing: {os.path.basename(binding_file)}")
            
            # Step 1: Run Quacky to extract regex_from_dfa
            logging.info("  Step 1: Extracting regex from DFA...")
            extract_result = run_quacky_gcp_extract(quacky_path, gcp_roles, binding_file, bound)
            
            if extract_result['satisfiability'] != 'sat' or not extract_result['regex_from_dfa']:
                logging.error(f"  STOPPING: No regex extracted from Quacky (satisfiability: {extract_result['satisfiability']})")
                logging.error(f"  Cannot proceed without regex_from_dfa for comparison.")
                logging.error(f"  Raw stdout: {extract_result.get('raw_stdout', 'N/A')[:500]}")
                logging.error(f"  Raw stderr: {extract_result.get('raw_stderr', 'N/A')[:500]}")
                results.append({
                    'cloud': 'gcp',
                    'file': os.path.basename(binding_file),
                    'satisfiability': extract_result['satisfiability'],
                    'regex_from_dfa': None,
                    'regex_from_llm': None,
                    'jaccard_similarity': None,
                    'error': 'No regex extracted - cannot compare'
                })
                # Stop processing this file, but continue to next file
                continue
            
            regex_dfa = extract_result['regex_from_dfa']
            logging.info(f"  Regex DFA extracted (length: {len(regex_dfa)})")
            logging.debug(f"  Regex DFA: {regex_dfa[:200]}..." if len(regex_dfa) > 200 else f"  Regex DFA: {regex_dfa}")
            
            # Step 2: Prompt LLM to summarize the regex
            logging.info("  Step 2: Prompting LLM for summarized regex...")
            try:
                regex_llm = prompt_llm_for_summary(regex_dfa, client)
                logging.info(f"  Regex LLM generated (length: {len(regex_llm)})")
                logging.debug(f"  Regex LLM: {regex_llm}")
            except Exception as e:
                logging.error(f"  LLM call failed: {e}")
                results.append({
                    'cloud': 'gcp',
                    'file': os.path.basename(binding_file),
                    'satisfiability': extract_result['satisfiability'],
                    'regex_from_dfa': regex_dfa,
                    'regex_from_llm': None,
                    'jaccard_similarity': None,
                    'error': str(e)
                })
                continue
            
            # Step 3: Write LLM regex to temp file
            llm_regex_file = os.path.join(temp_dir, f'llm_regex_gcp_{idx}.txt')
            with open(llm_regex_file, 'w') as f:
                f.write(regex_llm)
            logging.debug(f"  Wrote LLM regex to: {llm_regex_file}")
            
            # Step 4: Run Quacky with --compareregex to compute Jaccard similarity
            logging.info("  Step 3: Running Quacky --compareregex to compute Jaccard similarity...")
            compare_result = run_quacky_gcp_compare(
                quacky_path, gcp_roles, binding_file, llm_regex_file, bound
            )
            
            result = {
                'cloud': 'gcp',
                'file': os.path.basename(binding_file),
                'solve_time_ms': compare_result['solve_time'],
                'satisfiability': compare_result['satisfiability'],
                'count_time_ms': compare_result['count_time'],
                'lg_requests': compare_result['lg_requests'],
                'regex_from_dfa': regex_dfa,
                'regex_from_llm': regex_llm,
                'baseline_regex_count': compare_result['baseline_regex_count'],
                'synthesized_regex_count': compare_result['synthesized_regex_count'],
                'baseline_not_synthesized': compare_result['baseline_not_synthesized'],
                'not_baseline_synthesized': compare_result['not_baseline_synthesized'],
                'jaccard_numerator': compare_result['jaccard_numerator'],
                'jaccard_denominator': compare_result['jaccard_denominator'],
                'jaccard_similarity': compare_result['jaccard_similarity'],
                'ops_regex_from_dfa': compare_result['ops_regex_from_dfa'],
                'ops_regex_from_llm': compare_result['ops_regex_from_llm'],
                'length_regex_from_dfa': compare_result['length_regex_from_dfa'],
                'length_regex_from_llm': compare_result['length_regex_from_llm'],
            }
            
            logging.info(f"  Results:")
            logging.info(f"    Jaccard Similarity: {compare_result['jaccard_similarity']}")
            logging.info(f"    Baseline (DFA) Count: {compare_result['baseline_regex_count']}")
            logging.info(f"    Synthesized (LLM) Count: {compare_result['synthesized_regex_count']}")
            logging.info(f"    DFA regex length: {compare_result['length_regex_from_dfa']}")
            logging.info(f"    LLM regex length: {compare_result['length_regex_from_llm']}")
            
            results.append(result)
    
    # Write results to CSV if requested
    if output_csv and results:
        write_results_csv(results, output_csv)
    
    # Print summary
    print_summary(results)
    
    # Cleanup temp directory
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    logging.debug(f"Cleaned up temp directory: {temp_dir}")
    
    return results


def write_results_csv(results: list, output_path: str):
    """Write results to a CSV file."""
    if not results:
        return
    
    fieldnames = [
        'cloud', 'file', 'solve_time_ms', 'satisfiability', 'count_time_ms',
        'lg_requests', 'jaccard_similarity', 'jaccard_numerator', 'jaccard_denominator',
        'baseline_regex_count', 'synthesized_regex_count', 
        'baseline_not_synthesized', 'not_baseline_synthesized',
        'ops_regex_from_dfa', 'ops_regex_from_llm',
        'length_regex_from_dfa', 'length_regex_from_llm',
        'regex_from_dfa', 'regex_from_llm'
    ]
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)
    
    logging.info(f"Results written to: {output_path}")


def print_summary(results: list):
    """Print a summary of all results."""
    if not results:
        logging.info("No results to summarize.")
        return
    
    logging.info("")
    logging.info("=" * 60)
    logging.info("SUMMARY")
    logging.info("=" * 60)
    
    # Filter results with valid similarities
    valid_results = [r for r in results if r.get('jaccard_similarity') is not None]
    
    if not valid_results:
        logging.info("No valid results with Jaccard similarity computed.")
        return
    
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
    else:
        avg_jaccard = min_jaccard = max_jaccard = 0
    
    logging.info(f"Total policies processed: {len(results)}")
    logging.info(f"Successful comparisons: {len(valid_results)}")
    logging.info(f"")
    logging.info(f"Jaccard Similarity Statistics:")
    logging.info(f"  Average: {avg_jaccard:.4f}")
    logging.info(f"  Min: {min_jaccard:.4f}")
    logging.info(f"  Max: {max_jaccard:.4f}")
    
    # Per-cloud stats
    for cloud in ['azure', 'gcp']:
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


def main():
    parser = argparse.ArgumentParser(
        description='Process cloud policies, extract regexes via Quacky, summarize with LLM, and compute Jaccard similarity',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test mode (process one policy from each cloud)
  python3 regex_summarizer.py --test -q /path/to/quacky.py -ard role_def.json -aad ./assignments/

  # Full run with logging
  python3 regex_summarizer.py -q /path/to/quacky.py -ard role_def.json -aad ./assignments/ -o results.csv --log run.log

  # Verbose mode for debugging
  python3 regex_summarizer.py --test -v -q /path/to/quacky.py -ard role_def.json -aad ./assignments/
        """
    )
    
    # Quacky path
    parser.add_argument(
        '--quacky', '-q',
        required=True,
        help='Path to quacky.py'
    )
    
    # Azure arguments
    parser.add_argument(
        '--azure-role-def', '-ard',
        help='Path to Azure role definitions JSON file'
    )
    parser.add_argument(
        '--azure-assignments-dir', '-aad',
        help='Directory containing Azure role assignments (as0.json - as50.json)'
    )
    
    # GCP arguments
    parser.add_argument(
        '--gcp-roles', '-gr',
        help='Path to GCP roles JSON file'
    )
    parser.add_argument(
        '--gcp-bindings-dir', '-gbd',
        help='Directory containing GCP role bindings (bd0.json - bd50.json)'
    )
    
    # General arguments
    parser.add_argument(
        '--bound', '-b',
        type=int,
        default=150,
        help='Bound parameter for Quacky (default: 150)'
    )
    parser.add_argument(
        '--output', '-o',
        help='Output CSV file path'
    )
    parser.add_argument(
        '--api-key',
        help='Anthropic API key (or set ANTHROPIC_API_KEY env var)'
    )
    
    # Test and logging arguments
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
    
    # Setup logging
    log_file = args.log
    if args.test and not log_file:
        # Auto-create log file for test runs
        log_file = f"test_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    setup_logging(log_file=log_file, verbose=args.verbose)
    
    logging.info("=" * 60)
    logging.info("Regex Summarizer for Cloud Policies")
    logging.info("=" * 60)
    logging.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logging.info(f"Test mode: {args.test}")
    logging.info(f"Verbose: {args.verbose}")
    logging.info(f"Quacky path: {args.quacky}")
    if args.azure_role_def:
        logging.info(f"Azure role definitions: {args.azure_role_def}")
        logging.info(f"Azure assignments dir: {args.azure_assignments_dir}")
    if args.gcp_roles:
        logging.info(f"GCP roles: {args.gcp_roles}")
        logging.info(f"GCP bindings dir: {args.gcp_bindings_dir}")
    logging.info(f"Bound: {args.bound}")
    if args.output:
        logging.info(f"Output CSV: {args.output}")
    
    # Validate arguments
    if not args.azure_role_def and not args.gcp_roles:
        parser.error("At least one of --azure-role-def or --gcp-roles must be provided")
    
    if args.azure_role_def and not args.azure_assignments_dir:
        parser.error("--azure-assignments-dir is required when --azure-role-def is provided")
    
    if args.gcp_roles and not args.gcp_bindings_dir:
        parser.error("--gcp-bindings-dir is required when --gcp-roles is provided")
    
    # Run processing
    results = process_policies(
        quacky_path=args.quacky,
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