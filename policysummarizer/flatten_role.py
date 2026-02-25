"""Flatten Azure role definitions to Quacky-compatible format."""

import json
import sys

def flatten_role(role: dict) -> dict:
    perms = role.get('permissions', [{}])[0]
    name = role.get('name', '')
    
    return {
        "AssignableScopes": role.get('assignableScopes', ['/']),
        "Description": role.get('description', ''),
        "Id": f"/subscriptions/00000000-0000-0000-0000-000000000000/providers/Microsoft.Authorization/roleDefinitions/{name}",
        "Name": name,
        "Actions": perms.get('actions', []),
        "NotActions": perms.get('notActions', []),
        "DataActions": perms.get('dataActions', []),
        "NotDataActions": perms.get('notDataActions', []),
        "RoleName": role.get('roleName', ''),
        "RoleType": role.get('roleType', 'BuiltInRole'),
        "Type": "Microsoft.Authorization/roleDefinitions"
    }

def main():
    if len(sys.argv) < 3:
        print("Usage: python flatten_azure_roles.py <input.json> <output.json>")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        roles = json.load(f)

    flattened = [flatten_role(r) for r in roles]

    with open(sys.argv[2], 'w') as f:
        json.dump(flattened, f, indent=2)

    print(f"Flattened {len(flattened)} roles -> {sys.argv[2]}")

if __name__ == "__main__":
    main()