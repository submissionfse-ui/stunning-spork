"""
Combine individual GCP role JSON files into a single array for Quacky.

Reads all *.json files from quacky/iam-dataset/gcp/roles/ and combines them
into a single JSON array with the format Quacky expects:
[
  {
    "name": "roles/...",
    "title": "...",
    "includedPermissions": [...]
  },
  ...
]
"""

import json
import os
import sys
from pathlib import Path

def main():
    # Path to the roles directory
    roles_dir = Path("quacky/iam-dataset/gcp/roles")

    if not roles_dir.exists():
        print(f"Error: Directory not found: {roles_dir}")
        sys.exit(1)

    # Output file
    output_file = Path("quacky/iam-dataset/gcp/combined_roles.json")

    print(f"Reading role files from: {roles_dir}")

    # Collect all roles
    roles = []
    role_files = sorted(roles_dir.glob("*.json"))

    for role_file in role_files:
        try:
            with open(role_file) as f:
                role = json.load(f)
                roles.append(role)
        except Exception as e:
            print(f"Warning: Failed to load {role_file}: {e}")
            continue

    print(f"Loaded {len(roles)} roles")

    # Write combined roles
    with open(output_file, 'w') as f:
        json.dump(roles, f, indent=2)

    print(f"Combined roles written to: {output_file}")
    print(f"\nYou can now use this file with Quacky:")
    print(f"  -gr {output_file}")

if __name__ == "__main__":
    main()
