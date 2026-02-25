"""
Synthesize realistic GCP IAM role bindings from predefined roles.
Generates N JSON files, each containing ONE IAM binding in Quacky-compatible format.
"""

import json
import os
import random
import sys

# GCP organizational hierarchy examples
ORGANIZATIONS = [
    "myorg",
    "contoso-org",
    "acme-corp",
]

FOLDERS = [
    "engineering",
    "data",
    "security",
    "platform",
    "production",
    "development",
]

PROJECTS = [
    "prod-web-12345",
    "dev-analytics-67890",
    "staging-api-11111",
    "shared-services-22222",
    "ml-training-33333",
    "data-warehouse-44444",
]


def generate_principals():
    """Generate realistic GCP principal identifiers."""
    principals = []

    # Service accounts
    service_accounts = [
        "github-actions@prod-web-12345.iam.gserviceaccount.com",
        "terraform-automation@shared-services-22222.iam.gserviceaccount.com",
        "dataflow-worker@prod-web-12345.iam.gserviceaccount.com",
        "gke-node-pool@prod-web-12345.iam.gserviceaccount.com",
        "cloud-function-invoker@prod-web-12345.iam.gserviceaccount.com",
        "bigquery-scheduler@data-warehouse-44444.iam.gserviceaccount.com",
        "backup-service@shared-services-22222.iam.gserviceaccount.com",
        "ml-training-pipeline@ml-training-33333.iam.gserviceaccount.com",
    ]

    # Users
    users = [
        "alice.johnson@contoso.com",
        "bob.smith@contoso.com",
        "carol.williams@contoso.com",
        "david.brown@contoso.com",
        "emma.davis@contoso.com",
        "frank.miller@contoso.com",
        "grace.lee@contoso.com",
    ]

    # Groups
    groups = [
        "platform-engineers@contoso.com",
        "devops-admins@contoso.com",
        "security-team@contoso.com",
        "developers@contoso.com",
        "data-analysts@contoso.com",
        "ml-engineers@contoso.com",
    ]

    # Simple identifiers (like "foo" in the example)
    simple_ids = [
        "admin-user",
        "service-account-1",
        "automation-principal",
        "viewer-group",
        "editor-user",
    ]

    principals.extend(service_accounts)
    principals.extend(users)
    principals.extend(groups)
    principals.extend(simple_ids)

    return principals


def generate_level() -> str:
    """Generate a GCP resource hierarchy level path."""
    org = random.choice(ORGANIZATIONS)

    # Randomly choose scope level
    scope_type = random.choices(
        ['organization', 'folder', 'project'],
        weights=[0.2, 0.3, 0.5]
    )[0]

    if scope_type == 'organization':
        return f"/{org}"
    elif scope_type == 'folder':
        folder = random.choice(FOLDERS)
        return f"/{org}/{folder}"
    else:  # project
        folder = random.choice(FOLDERS)
        project = random.choice(PROJECTS)
        return f"/{org}/{folder}/{project}"


def generate_single_binding(role: dict, principals: list) -> dict:
    """
    Generate a single IAM binding for a role in Quacky-compatible format.

    Expected output format:
    {
        "bindings": [
            {
                "level": "/myorg/myfolder/myproject",
                "members": ["foo"],
                "role": "roles/storage.objectViewer"
            }
        ]
    }
    """
    level = generate_level()

    # Randomly select 1-3 members for this binding
    num_members = random.choices([1, 2, 3], weights=[0.7, 0.2, 0.1])[0]
    members = random.sample(principals, num_members)

    return {
        "bindings": [
            {
                "level": level,
                "members": members,
                "role": role['name']
            }
        ]
    }


def main():
    # Default to combined_roles.json (with includedPermissions) in the quacky GCP dataset
    default_roles_file = "quacky/iam-dataset/gcp/combined_roles.json"

    if len(sys.argv) < 2:
        print("Usage: python binding_generator.py <num_files> [roles_file.json]")
        print(f"Example: python binding_generator.py 20")
        print(f"         python binding_generator.py 20 {default_roles_file}")
        print(f"\nIf roles_file is not specified, will use: {default_roles_file}")
        sys.exit(1)

    num_files = int(sys.argv[1])
    roles_file = sys.argv[2] if len(sys.argv) > 2 else default_roles_file

    # Check if file exists
    if not os.path.exists(roles_file):
        print(f"Error: Roles file not found: {roles_file}")
        sys.exit(1)

    with open(roles_file) as f:
        roles = json.load(f)

    if isinstance(roles, dict) and 'roles' in roles:
        roles = roles['roles']

    original_count = len(roles)

    # Filter out roles without includedPermissions (ALPHA/BETA roles, deprecated, etc.)
    roles = [r for r in roles if 'includedPermissions' in r and len(r.get('includedPermissions', [])) > 0]

    filtered_count = original_count - len(roles)
    if filtered_count > 0:
        print(f"Filtered out {filtered_count} roles without permissions (ALPHA/BETA/deprecated)")

    print(f"Loaded {len(roles)} valid role definitions from {roles_file}")
    print(f"Generating {num_files} binding files (1 binding per file)...")

    principals = generate_principals()

    output_dir = "bindings"
    os.makedirs(output_dir, exist_ok=True)

    for i in range(num_files):
        role = roles[i % len(roles)]
        binding = generate_single_binding(role, principals)

        # Use simple naming: bd0.json, bd1.json, bd2.json, etc.
        filename = f"{output_dir}/bd{i}.json"

        with open(filename, 'w') as f:
            json.dump(binding, f, indent=2)

        print(f"  [{i+1}/{num_files}] {filename} -> {role.get('title', role.get('name'))}")

    print(f"\nGenerated {num_files} files in '{output_dir}/'")


if __name__ == "__main__":
    main()
