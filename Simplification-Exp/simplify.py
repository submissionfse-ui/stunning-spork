import subprocess
import anthropic
import json
import logging
import os
import re
import signal
import csv
from tqdm import tqdm

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("regex_simplifier.log"), logging.StreamHandler()])

# Initialize Anthropic client with an api key


model_name = "claude-3-5-sonnet-20240620"

# File paths (using the original code's paths)
policy_folder = "/home/adarsh/Documents/Experiments/Dataset"
quacky_path = "quacky/src/quacky.py"
working_directory = "quacky/src/"
response_file_path = "quacky/src/response.txt"
progress_file_path = "Simplification-Exp/s_progress.json"
result_csv_path = "Simplification-Exp/simplify.csv"

def generate_regex_from_dfa(policy_path):
    command = [
        "python3", quacky_path,
        "-p1", policy_path,
        "-b", "100",
        "-pr"
    ]
    result = subprocess.run(command, cwd=working_directory, capture_output=True, text=True)
    
    if result.returncode != 0:
        logging.error(f"Quacky regex generation failed: {result.stderr}")
        return None

    # Extract regex_from_dfa from the output
    match = re.search(r'regex_from_dfa: (.+)', result.stdout)
    if match:
        return match.group(1).strip()
    else:
        logging.error("Failed to extract regex_from_dfa from Quacky output")
        return None

def simplify_regex(regex):
    system_prompt = """
    You are an expert in regular expressions. Your task is to simplify the given regex to make it more visually understandable while ensuring it still accepts the same set of strings as the original regex. Provide ONLY the simplified regex pattern itself, without any explanations or additional text.
    """
    
    user_prompt = f"Simplify this regex to make it more visually understandable while ensuring it still accepts the same set of strings:\n\n{regex}"

    try:
        response = client.messages.create(
            model=model_name,
            max_tokens=1000,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        simplified_regex = response.content[0].text.strip()
        return simplified_regex
    except Exception as e:
        logging.error(f"Error calling Anthropic API for regex simplification: {str(e)}")
        return None

def timeout_handler(signum, frame):
    raise TimeoutError("Analysis took too long")

def run_final_analysis(policy_path, timeout=2000):
    command = [
        "python3", quacky_path,
        "-p1", policy_path,
        "-b", "100",
        "-cr", response_file_path
    ]

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)

    try:
        result = subprocess.run(command, cwd=working_directory, capture_output=True, text=True)
        signal.alarm(0)

        if result.returncode != 0 or "FATAL ERROR FROM ABC" in result.stderr:
            raise Exception("Quacky analysis failed")

        logging.info("Quacky Final Analysis Output:")
        logging.info(result.stdout)
        if result.stderr:
            logging.error(f"Errors: {result.stderr}")
        return result.stdout
    except TimeoutError:
        logging.error(f"Final analysis for policy {policy_path} timed out after {timeout} seconds.")
        return "TIMEOUT"
    except Exception as e:
        logging.error(f"Error in final analysis: {str(e)}")
        return None
    finally:
        signal.alarm(0)

def parse_analysis(analysis):
    fields = {
        'Baseline Regex Count': None,
        'Synthesized Regex Count': None,
        'Baseline_Not_Synthesized Count': None,
        'Not_Baseline_Synthesized_Count': None,
        'jaccard_numerator': None,
        'jaccard_denominator': None
    }

    for field in fields:
        match = re.search(rf'{field}\s*:\s*(.*?)(?:\n|$)', analysis)
        if match:
            fields[field] = match.group(1).strip()

    return fields

def process_policy(policy_path):
    regex_from_dfa = generate_regex_from_dfa(policy_path)
    if not regex_from_dfa:
        logging.error("Failed to generate regex from DFA")
        return None

    # Simplify the regex using Claude
    simplified_regex = simplify_regex(regex_from_dfa)
    if not simplified_regex:
        logging.error("Failed to simplify regex using Claude")
        return None

    with open(response_file_path, 'w') as file:
        file.write(simplified_regex)

    # Run final analysis
    analysis_output = run_final_analysis(policy_path)
    if not analysis_output:
        logging.error("Final analysis failed")
        return None

    # Parse the analysis output
    parsed_analysis = parse_analysis(analysis_output)

    return {
        "Original Regex": regex_from_dfa,
        "Simplified Regex": simplified_regex,
        "Analysis": parsed_analysis
    }

def get_progress():
    try:
        if os.path.exists(progress_file_path):
            with open(progress_file_path, 'r') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
                else:
                    logging.warning("Progress file is empty. Starting from the beginning.")
    except json.JSONDecodeError:
        logging.warning("Invalid JSON in progress file. Starting from the beginning.")
    except Exception as e:
        logging.error(f"Error reading progress file: {str(e)}. Starting from the beginning.")
    
    return {"last_processed": 0}


def update_progress(last_processed):
    with open(progress_file_path, 'w') as f:
        json.dump({"last_processed": last_processed}, f)


def write_results_to_csv(results):
    # Define the columns for our CSV
    columns = [
        "Policy", "Original Regex", "Simplified Regex",
        "Baseline Regex Count", "Synthesized Regex Count",
        "Baseline_Not_Synthesized Count", "Not_Baseline_Synthesized_Count",
        "jaccard_numerator", "jaccard_denominator"
    ]


    file_exists = os.path.isfile(result_csv_path)

    # Open the CSV file in append mode
    with open(result_csv_path, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=columns)

  
        if not file_exists:
            writer.writeheader()

      
        for result in results:
            row = {
                "Policy": result["Policy"],
                "Original Regex": result["Original Regex"],
                "Simplified Regex": result["Simplified Regex"],
                "Baseline Regex Count": result["Analysis"]["Baseline Regex Count"],
                "Synthesized Regex Count": result["Analysis"]["Synthesized Regex Count"],
                "Baseline_Not_Synthesized Count": result["Analysis"]["Baseline_Not_Synthesized Count"],
                "Not_Baseline_Synthesized_Count": result["Analysis"]["Not_Baseline_Synthesized_Count"],
                "jaccard_numerator": result["Analysis"]["jaccard_numerator"],
                "jaccard_denominator": result["Analysis"]["jaccard_denominator"]
            }
            writer.writerow(row)

    logging.info(f"Results appended to {result_csv_path}")


def main():
    policy_files = sorted([f for f in os.listdir(policy_folder) if f.endswith('.json')])
    total_policies = len(policy_files)

    while True:
        try:
            num_policies = int(input(f"Enter the number of policies to process (1-{total_policies}) or -1 for all remaining policies: "))
            if num_policies == -1 or (1 <= num_policies <= total_policies):
                break
            else:
                print(f"Please enter a number between 1 and {total_policies}, or -1 for all remaining policies.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")

    progress = get_progress()
    start_index = progress["last_processed"]

    start_index = max(0, min(start_index, total_policies - 1))

    print(f"Starting from policy number {start_index + 1}")

    end_index = total_policies if num_policies == -1 else min(start_index + num_policies, total_policies)

    results = []

    for i in tqdm(range(start_index, end_index), desc="Processing policies"):
        policy_file = policy_files[i]
        policy_path = os.path.join(policy_folder, policy_file)
        logging.info(f"\nProcessing policy: {policy_file}")

        result = process_policy(policy_path)
        if result:
            result["Policy"] = policy_file
            results.append(result)

        update_progress(i + 1)

        write_results_to_csv([result])

    logging.info("Processing complete. Results saved to simplify.csv")
    print(f"Processed {end_index - start_index} policies. Next run will start from policy number {min(end_index + 1, total_policies)}")

if __name__ == "__main__":
    main()
