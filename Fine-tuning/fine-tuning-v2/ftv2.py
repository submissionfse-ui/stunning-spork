import subprocess
import pandas as pd
import os
import openai
import json
import logging
from tqdm import tqdm
import signal
import re
import time


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler("policy_analysis.log"), logging.StreamHandler()])

#initialize open ai client with api key
model_id = "ft:gpt-4o-mini-2024-07-18:personal::A5b7jUfX"

# Define paths
policy_folder = "Dataset"
quacky_path = "quacky/src/quacky.py"
working_directory = "quacky/src/"
response_file_path = "quacky/src/response.txt"
result_table_path = "Fine-tuning/fine-tuning-v2/policy_analysis_fine_tuned.csv"
generated_policy_path = "quacky/src/gen_pol.json"
p1_not_p2_models_path = "quacky/src/P1_not_P2.models"
progress_file_path = "Fine-tuning/fine-tuning-v2/ft-progress.json"

def read_policy_file(file_path):
    with open(file_path, 'r') as file:
        return file.read()




def generate_strings(policy_path, size):
    command = [
        "python3", quacky_path,
        "-p1", policy_path,
        "-b", "100",
        "-m", str(size),
        "-m1", "20",
        "-m2", "100"
    ]
    
    result = subprocess.run(command, cwd=working_directory, capture_output=True, text=True)
    logging.info("Getting strings:")
    if result.stderr:
        logging.error(f"Errors: {result.stderr}")
    
    with open(p1_not_p2_models_path, 'r') as file:
        strings = file.read()
    
    return strings

def generate_regex(strings):
    try:
        response = client.chat.completions.create(
            model=model_id,
            messages=[
                {"role": "system", "content": "You are a regex generation assistant."},
                {"role": "user", "content": f"Generate a regex for the following strings, the regex should be optimal and not overly permissive but should accept all the strings provided:\n{strings}"}
            ],
            max_tokens=1000
        )
        regex = response.choices[0].message.content.strip()
        
        with open(response_file_path, "w") as output_file:
            output_file.write(regex)
        
        logging.info(f"Regex generated and written to {response_file_path}")
        return regex
    except openai.OpenAIError as e:
        logging.error(f"OpenAI API error: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error in regex generation: {str(e)}")
        return None
    

def timeout_handler(signum, frame):
    raise TimeoutError("Analysis took too long")

def run_final_analysis(policy_path, timeout=300):  # 5 minutes timeout
    command = [
        "python3", quacky_path,
        "-p1", policy_path,
        "-b", "100",
        "-cr", response_file_path
    ]
    
    # Setting up a timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(timeout)
    
    try:
        result = subprocess.run(command, cwd=working_directory, capture_output=True, text=True)
        signal.alarm(0)
        
        logging.info("Quacky Final Analysis Output:")
        logging.info(result.stdout)
        if result.stderr:
            logging.error(f"Errors: {result.stderr}")
        return result.stdout
    except TimeoutError:
        logging.error(f"Final analysis for policy {policy_path} timed out after {timeout} seconds.")
        return "TIMEOUT"
    finally:
        #Ensure the alarm is canceled even if an exception occurs
        signal.alarm(0)


def process_policy(policy_path, size):
    start_time = time.time()
    errors = []
    original_policy = ""
    regex = ""
    exp2_raw_output = ""


    policy_number = os.path.basename(policy_path).split('.')[0]

    try:
        original_policy = read_policy_file(policy_path)
    except Exception as e:
        errors.append(f"Error reading policy file: {str(e)}")

    if not errors:
        try:
            strings = generate_strings(policy_path, size)
        except Exception as e:
            errors.append(f"Error generating strings: {str(e)}")
        
        if strings:
            try:
                regex = generate_regex(strings)
            except Exception as e:
                errors.append(f"Error generating regex: {str(e)}")
            
            if regex:
                try:
                    exp2_raw_output = run_final_analysis(policy_path)
                except Exception as e:
                    errors.append(f"Error in final analysis: {str(e)}")
            else:
                errors.append("Failed to generate regex")
        else:
            errors.append("Failed to generate strings")

    processing_time = time.time() - start_time
    return {
        "Policy Number": policy_number,
        "model_name": model_id,  # Update this to use the fine-tuned model ID
        "Original Policy": original_policy,
        "Size": size,
        "Regex from llm": regex,
        "Experiment 2_Analysis": exp2_raw_output,
        "Errors": "; ".join(errors) if errors else "",
        "Processing Time (s)": round(processing_time, 2)
    }

def get_progress():
    if os.path.exists(progress_file_path):
        with open(progress_file_path, 'r') as f:
            return json.load(f)
    return {"last_processed": 0}

def update_progress(last_processed):
    with open(progress_file_path, 'w') as f:
        json.dump({"last_processed": last_processed}, f)

if __name__ == "__main__":
    def sort_key(filename):
        match = re.search(r'(\d+)', filename)
        return int(match.group(1)) if match else 0

    policy_files = sorted([f for f in os.listdir(policy_folder) if f.endswith('.json')], key=sort_key)
    total_policies = len(policy_files)
    
    size = 1000  # You can make this configurable if needed

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


    required_columns = [
        "Policy Number", "model_name", "Original Policy", "Size", "Regex from llm", 
        "Experiment 2_Analysis", "Errors", "Processing Time (s)"
    ]

    if not os.path.exists(result_table_path) or os.stat(result_table_path).st_size == 0:
        result_table = pd.DataFrame(columns=required_columns)
    else:
        try:
            result_table = pd.read_csv(result_table_path)
            if result_table.empty or not all(col in result_table.columns for col in required_columns):
                result_table = pd.DataFrame(columns=required_columns)
        except pd.errors.EmptyDataError:
            result_table = pd.DataFrame(columns=required_columns)
        
        for column in set(required_columns) - set(result_table.columns):
            result_table[column] = ""

    end_index = total_policies if num_policies == -1 else min(start_index + num_policies, total_policies)

    for i in tqdm(range(start_index, end_index), desc="Processing policies"):
        if i < total_policies:
            policy_file = policy_files[i]
            policy_path = os.path.join(policy_folder, policy_file)
            logging.info(f"\nProcessing policy: {policy_file}")
            
            try:
                new_entry = process_policy(policy_path, size)
                
                result_table = pd.concat([result_table, pd.DataFrame([new_entry])], ignore_index=True)
                result_table.to_csv(result_table_path, index=False)
                logging.info(f"Results table updated and saved to {result_table_path}")
                update_progress(i + 1)
            except Exception as e:
                logging.error(f"Error processing policy {policy_file}: {str(e)}")
                continue
        else:
            logging.warning(f"Index {i} is out of range. Stopping processing.")
            break

    logging.info("\nProcessing complete. Final results table saved to: " + result_table_path)
    print(f"Processed {end_index - start_index} policies. Next run will start from policy number {min(end_index + 1, total_policies)}")
