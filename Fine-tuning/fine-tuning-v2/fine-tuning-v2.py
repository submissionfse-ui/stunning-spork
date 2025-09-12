import os
import json
import subprocess
import re
import logging
from tqdm import tqdm
import anthropic
import signal

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("fine_tuning_dataset_generation.log"), logging.StreamHandler()])

# Initialize Anthropic client with api key
model_name = "claude-3-5-sonnet-20240620"

policy_folder = "Dataset"
quacky_path = "quacky.py"
working_directory = "quacky/src/"
response_file_path = "quacky/src/response.txt"
p1_not_p2_models_path = "quacky/src/P1_not_P2.models"
fine_tuning_dataset_path = "Fine-tuning/fine-tuning-v2/fine_tuning_dataset.jsonl"
progress_file_path = "Fine-tuning/fine-tuning-v2/progress.json"

def generate_strings(policy_path, size=1000):
    command = [
        "python3", quacky_path,
        "-p1", policy_path,
        "-b", "100",
        "-m", str(size),
        "-m1", "20",
        "-m2", "100"
    ]
    
    result = subprocess.run(command, cwd=working_directory, capture_output=True, text=True)
    logging.info("Generating strings")
    if result.stderr:
        logging.error(f"Errors: {result.stderr}")
    
    with open(p1_not_p2_models_path, 'r') as file:
        strings = file.read()
    
    return strings

def generate_regex(strings):
    system_prompt = """
    When asked to give a regex, provide ONLY the regex pattern itself. Do not include any explanations, markdown formatting, or additional text. The response should be just the regex pattern, nothing else. This is a highly critical application and it is imperative to get this right. Just give me the regex.
    
    Example bad(terrible) response(DO NOT WANT THIS IN ANY CASE):
    
    "Here is the regex pattern based on the provided set of strings: (?:foo|bar)[a-z0-9.-]{0,60}"


    Example good response:

    "(?:foo|bar)[a-z0-9.-]{0,60}"

    """
    prompt = f"Give me a single regex that accepts each string in the following set of strings, Make sure that you carefully go through each string before forming the regex. it should be close to optimal and not super permissive:\n\n{strings}\n\n , Example bad(terrible) response(DO NOT WANT THIS IN ANY CASE): Here is the regex pattern based on the provided set of strings: arn:aws:ec2:us-east-1:(?:\d:?)?(?:(?:key-pair|subnet|security-group|network-interface|volume|instance)|image/ami-)[!-~], Example good response: arn:aws:ec2:us-east-1:(?:\d:?)?(?:(?:key-pair|subnet|security-group|network-interface|volume|instance)|image/ami-)[!-~], (This response acts as an input for a regex analysis application so if you give me any sort of additional text along with the regex like Here's a regex matching the strings , etc. etc. the application will fail, so only reply with the regex and nothing else.)"


    try:
        response = client.messages.create(
            model=model_name,
            max_tokens=1000,
            system=system_prompt,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        regex = response.content[0].text.strip()
        regex = regex.lstrip('^').rstrip('$')
        with open(response_file_path, "w") as output_file:
            output_file.write(regex)
        
        logging.info(f"Regex generated and written to {response_file_path}")
        return regex
    except Exception as e:
        logging.error(f"Error calling Anthropic API for regex generation: {str(e)}")
        return None

def timeout_handler(signum, frame):
    raise TimeoutError("Analysis took too long")

def run_analysis(policy_path, timeout=2000):
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

        if result.returncode != 0:
            raise Exception("Quacky analysis failed")

        logging.info("Quacky Analysis Output:")
        logging.info(result.stdout)
        if result.stderr:
            logging.error(f"Errors: {result.stderr}")
        return result.stdout
    except TimeoutError:
        logging.error(f"Analysis for policy {policy_path} timed out after {timeout} seconds.")
        return None
    except Exception as e:
        logging.error(f"Error in analysis: {str(e)}")
        return None
    finally:
        signal.alarm(0)

def is_good_performance(analysis_output):
    jaccard_numerator = re.search(r'jaccard_numerator\s*:\s*(\d+)', analysis_output)
    jaccard_denominator = re.search(r'jaccard_denominator\s*:\s*(\d+)', analysis_output)
    
    if jaccard_numerator and jaccard_denominator:
        num_digits_numerator = len(jaccard_numerator.group(1))
        num_digits_denominator = len(jaccard_denominator.group(1))
        return num_digits_numerator >= num_digits_denominator - 1
    return False

def process_policy(policy_path):
    strings = generate_strings(policy_path)
    if not strings:
        return None

    regex = generate_regex(strings)
    if not regex:
        return None

    analysis_output = run_analysis(policy_path)
    if not analysis_output:
        return None

    if is_good_performance(analysis_output):
        return {
            "messages": [
                {"role": "system", "content": "You are a regex generation assistant."},
                {"role": "user", "content": f"Create an optimal regex for these set of strings:\n{strings}"},
                {"role": "assistant", "content": regex}
            ]
        }
    return None

def load_progress():
    if os.path.exists(progress_file_path):
        with open(progress_file_path, 'r') as f:
            return json.load(f)
    return {"last_processed_index": -1, "processed_policies": []}

def save_progress(progress):
    with open(progress_file_path, 'w') as f:
        json.dump(progress, f)

def main():
    progress = load_progress()
    last_processed_index = progress["last_processed_index"]
    processed_policies = set(progress["processed_policies"])

    policy_files = [f for f in os.listdir(policy_folder) if f.endswith('.json')]
    policy_files.sort()  # Ensure consistent ordering

    fine_tuning_data = []

    if os.path.exists(fine_tuning_dataset_path):
        user_input = input(f"The file {fine_tuning_dataset_path} already exists. Do you want to append to it? (y/n): ")
        if user_input.lower() == 'y':
            with open(fine_tuning_dataset_path, 'r') as f:
                fine_tuning_data = [json.loads(line) for line in f]
            print(f"Loaded {len(fine_tuning_data)} existing entries.")
        else:
            print("Starting with a new dataset.")

    for index, policy_file in enumerate(tqdm(policy_files[last_processed_index + 1:], initial=last_processed_index + 1, total=len(policy_files))):
        policy_path = os.path.join(policy_folder, policy_file)
        
        if policy_file in processed_policies:
            logging.info(f"Skipping already processed policy: {policy_file}")
            continue

        logging.info(f"\nProcessing policy: {policy_file}")

        result = process_policy(policy_path)
        if result:
            fine_tuning_data.append(result)

        # Update progress
        progress["last_processed_index"] = last_processed_index + index + 1
        progress["processed_policies"].append(policy_file)
        save_progress(progress)

        if len(fine_tuning_data) % 10 == 0:  # Save every 10 new entries
            with open(fine_tuning_dataset_path, 'w') as f:
                for item in fine_tuning_data:
                    f.write(json.dumps(item) + '\n')
            logging.info(f"Intermediate save: {len(fine_tuning_data)} entries saved to {fine_tuning_dataset_path}")

    # Final save
    with open(fine_tuning_dataset_path, 'w') as f:
        for item in fine_tuning_data:
            f.write(json.dumps(item) + '\n')

    logging.info(f"Fine-tuning dataset saved to: {fine_tuning_dataset_path}")
    print(f"Processed {len(policy_files)} policies. Created {len(fine_tuning_data)} entries in the fine-tuning dataset.")

if __name__ == "__main__":
    main()
