import csv
import os
import json

def read_policy_file(file_path):
    with open(file_path, 'r') as file:
        return file.read()

def add_policy_number_column(input_file, output_file, dataset_path):
    policy_files = sorted([f for f in os.listdir(dataset_path) if f.endswith('.json')])
    
    with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
        reader = csv.reader(infile)
        writer = csv.writer(outfile)

    
        header = next(reader)
        new_header = ['Policy Number'] + header
        writer.writerow(new_header)

        for row in reader:
            original_policy = row[1]  # Assuming "Original Policy" is the second column
            matching_policy = None

            for policy_file in policy_files:
                policy_path = os.path.join(dataset_path, policy_file)
                file_content = read_policy_file(policy_path)
                if file_content.strip() == original_policy.strip():
                    matching_policy = policy_file
                    break

            if matching_policy:
                new_row = [matching_policy] + row
            else:
                new_row = ["Unknown"] + row
                print(f"Warning: No matching policy file found for row {reader.line_num}")

            writer.writerow(new_row)

    print(f"Updated CSV saved to {output_file}")

if __name__ == "__main__":
    dataset_path = "/home/adarsh/Documents/Experiments/Dataset"
    input_csv = "/home/adarsh/Documents/Experiments/Fine-tuning/fine-tuning-v2/policy_analysis_fine_tuned.csv"
    output_csv = "/home/adarsh/Documents/Experiments/Fine-tuning/fine-tuning-v2/policy_analysis_fine_tuned_with_numbers.csv"
    add_policy_number_column(input_csv, output_csv, dataset_path)
