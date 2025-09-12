from openai import OpenAI
import time
import json
from pathlib import Path
import tiktoken

# Initialize the client with the API key


# Path to the JSONL file
file_path = Path("/home/adarsh/Documents/Experiments/Fine-tuning/fine-tuning-v2/fine_tuning_dataset.jsonl")

# Initialize the tokenizer
tokenizer = tiktoken.get_encoding("cl100k_base")  # This is the encoding used by GPT-4

def count_tokens(messages):
    """Count the number of tokens in a list of messages."""
    num_tokens = 0
    for message in messages:
        num_tokens += 4  # Every message follows <im_start>{role/name}\n{content}<im_end>\n
        for key, value in message.items():
            num_tokens += len(tokenizer.encode(value))
        num_tokens += 2  # Every reply is primed with <im_start>assistant
    return num_tokens

def validate_jsonl(file_path, max_tokens=65536):
    with open(file_path, 'r') as file:
        for idx, line in enumerate(file, 1):
            try:
                entry = json.loads(line)
                if 'messages' not in entry:
                    print(f"Error in line {idx}: 'messages' key is missing")
                    return False
                messages = entry['messages']
                if not isinstance(messages, list) or len(messages) < 2:
                    print(f"Error in line {idx}: 'messages' should be a list with at least 2 messages")
                    return False
                if not any(msg.get('role') == 'assistant' for msg in messages):
                    print(f"Error in line {idx}: No 'assistant' role found in messages")
                    return False
                
                # Check token count
                token_count = count_tokens(messages)
                if token_count > max_tokens:
                    print(f"Error in line {idx}: Token count ({token_count}) exceeds maximum ({max_tokens})")
                    return False
                
            except json.JSONDecodeError:
                print(f"Error in line {idx}: Invalid JSON")
                return False
    return True

# Validate the JSONL file
if not validate_jsonl(file_path):
    print("Validation failed. Please check your JSONL file and correct the errors.")
    exit(1)

print("Validation successful. Proceeding with file upload and fine-tuning job creation.")

# Upload the file
with file_path.open("rb") as file:
    response = client.files.create(
        file=file,
        purpose='fine-tune'
    )

file_id = response.id
print(f"File uploaded successfully. File ID: {file_id}")

# Create a fine-tuning job
response = client.fine_tuning.jobs.create(
    training_file=file_id,
    model="gpt-4o-mini-2024-07-18"
)

job_id = response.id
print(f"Fine-tuning job created. Job ID: {job_id}")

# Function to check the status of the fine-tuning job
def check_status(job_id):
    response = client.fine_tuning.jobs.retrieve(job_id)
    status = response.status
    print(f"Job status: {status}")
    return status, response

# Poll for status
status, job_response = check_status(job_id)
while status not in ["succeeded", "failed"]:
    time.sleep(60)  # Wait for 60 seconds before checking again
    status, job_response = check_status(job_id)

if status == "succeeded":
    print("Fine-tuning completed successfully!")
    fine_tuned_model = job_response.fine_tuned_model
    print(f"Fine-tuned model ID: {fine_tuned_model}")
else:
    print("Fine-tuning failed. Please check the OpenAI dashboard for more information.")
