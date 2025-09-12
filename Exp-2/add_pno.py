import csv
import os

def add_policy_number_column(input_file, output_file, dataset_path):
    policy_files = sorted([f for f in os.listdir(dataset_path) if f.endswith('.json')])
    policy_contents = {f: open(os.path.join(dataset_path, f), 'r').read().strip() for f in policy_files}
    
    with open(input_file, 'r') as infile, open(output_file, 'w', newline='') as outfile:
        reader = csv.reader(infile)
        writer = csv.writer(outfile)

        header = next(reader)
        new_header = ['Policy Number'] + header
        writer.writerow(new_header)

        for row in reader:
            original_policy = row[1]  # "Original Policy" is the second column
            matching_policy = next((f for f, content in policy_contents.items() 
                                    if content == original_policy), "Unknown")
            
            if matching_policy == "Unknown":
                print(f"Warning: No matching policy file found for row {reader.line_num}")

            new_row = [matching_policy] + row
            writer.writerow(new_row)

    print(f"Updated CSV saved to {output_file}")

if __name__ == "__main__":
    dataset_path = "/home/adarsh/Documents/Experiments/Dataset"
    input_csv = "Exp-2/Exp-2.csv"
    output_csv = "Exp-2/Exp-2_with_policy_numbers.csv"
    add_policy_number_column(input_csv, output_csv, dataset_path)
