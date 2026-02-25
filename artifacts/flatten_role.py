#!/usr/bin/env python3
"""
Flatten Azure role definitions from raw API format to Quacky-compatible format.
Converts nested 'permissions' array to flat Actions/NotActions/DataActions/NotDataActions.
"""

import json
import sys

def flatten_role(role: dict) -> dict:
    """Flatten a single role from raw format to Quacky format."""
    permissions = role.get('permissions', [{}])[0]
    name = role.get('name', '')
    
    return {
        "AssignableScopes": role.get('assignableScopes', ['/']),
        "Description": role.get('description', ''),
        "Id": f"/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/{name}",
        "Name": name,
        "Actions": permissions.get('actions', []),
        "NotActions": permissions.get('notActions', []),
        "DataActions": permissions.get('dataActions', []),
        "NotDataActions": permissions.get('notDataActions', []),
        "RoleName": role.get('roleName', ''),
        "RoleType": role.get('roleType', 'BuiltInRole'),
        "Type": role.get('type', 'Microsoft.Authorization/roleDefinitions')
    }

def main():
    if len(sys.argv) < 3:
        print("Usage: python flatten_azure_roles.py <input.json> <output.json>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    with open(input_file) as f:
        roles = json.load(f)

    if isinstance(roles, dict) and 'roles' in roles:
        roles = roles['roles']

    flattened = [flatten_role(r) for r in roles]

    with open(output_file, 'w') as f:
        json.dump(flattened, f, indent=2)

    print(f"Flattened {len(flattened)} roles -> {output_file}")

if __name__ == "__main__":
    main()