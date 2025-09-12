import os
from openai import OpenAI
import time
from pathlib import Path

# Initialize the client with the API key

# Path to your fine-tuning dataset
dataset_path = Path("fine_tuning_dataset.jsonl")

def upload_training_file(file_path: Path):
    try:
        with file_path.open("rb") as file:
            response = client.files.create(file=file, purpose="fine-tune")
        print(f"File uploaded successfully. File ID: {response.id}")
        return response.id
    except Exception as e:
        print(f"Error uploading file: {str(e)}")
        return None

def create_fine_tuning_job(file_id: str):
    try:
        job = client.fine_tuning.jobs.create(
            training_file=file_id,
            model="gpt-4o-mini-2024-07-18"
        )
        print(f"Fine-tuning job created. Job ID: {job.id}")
        return job.id
    except Exception as e:
        print(f"Error creating fine-tuning job: {str(e)}")
        return None

def monitor_fine_tuning_job(job_id: str):
    while True:
        try:
            job = client.fine_tuning.jobs.retrieve(job_id)
            print(f"Job status: {job.status}")
            if job.status in ["succeeded", "failed"]:
                return job
            time.sleep(60) 
        except Exception as e:
            print(f"Error retrieving job status: {str(e)}")
            time.sleep(60)  

def main():
    # Check if the dataset file exists
    if not dataset_path.exists():
        print(f"Error: The file {dataset_path} does not exist.")
        return

    # Upload the training file
    file_id = upload_training_file(dataset_path)
    if not file_id:
        return

    # Create the fine-tuning job
    job_id = create_fine_tuning_job(file_id)
    if not job_id:
        return

    # Monitor the job progress
    final_job = monitor_fine_tuning_job(job_id)

    if final_job.status == "succeeded":
        print(f"Fine-tuning complete. Fine-tuned model ID: {final_job.fine_tuned_model}")
    else:
        print("Fine-tuning job failed.")

if __name__ == "__main__":
    main()
