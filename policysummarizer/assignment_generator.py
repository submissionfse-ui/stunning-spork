"""
Synthesize realistic Azure RBAC role assignments from role definitions.
Generates N JSON files, each containing ONE assignment tailored to the role's permissions.
"""

import json
import uuid
import os
from datetime import datetime, timezone, timedelta
import random
import sys

TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"

SUBSCRIPTIONS = [
    {"id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "name": "Production"},
    {"id": "b2c3d4e5-f6a7-8901-bcde-f12345678901", "name": "Development"},
    {"id": "c3d4e5f6-a7b8-9012-cdef-123456789012", "name": "Staging"},
]

RESOURCE_GROUPS = [
    "rg-prod-eastus", "rg-prod-westus2", "rg-dev-eastus",
    "rg-staging-centralus", "rg-shared-services", "rg-security"
]

RESOURCE_MAPPINGS = {
    "Microsoft.ContainerRegistry": {
        "type": "registries",
        "names": ["acrprod001", "acrdev001", "acrshared", "acrcicd"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.ApiManagement": {
        "type": "service",
        "names": ["apim-prod-api", "apim-dev-gateway", "apim-partner-portal"],
        "principal_bias": ["ServicePrincipal", "Group"],
    },
    "Microsoft.Automation": {
        "type": "automationAccounts",
        "names": ["auto-runbooks-prod", "auto-patching", "auto-compliance"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.ContainerService": {
        "type": "managedClusters",
        "names": ["aks-prod-eastus", "aks-dev-cluster", "aks-staging-west"],
        "principal_bias": ["ServicePrincipal", "Group"],
    },
    "Microsoft.Insights": {
        "type": "components",
        "names": ["appi-prod-monitoring", "appi-dev-telemetry", "appi-logs"],
        "principal_bias": ["User", "Group"],
    },
    "Microsoft.RecoveryServices": {
        "type": "vaults",
        "names": ["rsv-backup-prod", "rsv-dr-secondary", "rsv-archive"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.Storage": {
        "type": "storageAccounts",
        "names": ["stproddata001", "stdevlogs002", "stbackup003"],
        "principal_bias": ["ServicePrincipal", "User"],
    },
    "Microsoft.Compute": {
        "type": "virtualMachines",
        "names": ["vm-prod-web01", "vm-dev-jump01", "vm-batch-worker"],
        "principal_bias": ["User", "Group"],
    },
    "Microsoft.Network": {
        "type": "virtualNetworks",
        "names": ["vnet-prod-hub", "vnet-dev-spoke", "vnet-dmz"],
        "principal_bias": ["Group"],
    },
    "Microsoft.KeyVault": {
        "type": "vaults",
        "names": ["kv-prod-secrets", "kv-dev-certs", "kv-shared-keys"],
        "principal_bias": ["ServicePrincipal", "User"],
    },
    "Microsoft.Cdn": {
        "type": "profiles",
        "names": ["cdn-prod-static", "cdn-global-assets"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.DocumentDB": {
        "type": "databaseAccounts",
        "names": ["cosmos-prod-data", "cosmos-dev-test", "cosmos-analytics"],
        "principal_bias": ["ServicePrincipal", "User"],
    },
    "Microsoft.DataFactory": {
        "type": "factories",
        "names": ["adf-prod-etl", "adf-dev-pipeline", "adf-ingest"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.CognitiveServices": {
        "type": "accounts",
        "names": ["cog-prod-openai", "cog-dev-vision", "cog-speech"],
        "principal_bias": ["ServicePrincipal", "User"],
    },
    "Microsoft.Maps": {
        "type": "accounts",
        "names": ["maps-prod-logistics", "maps-dev-test"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.Attestation": {
        "type": "attestationProviders",
        "names": ["attest-prod-tee", "attest-dev-sgx"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.Blockchain": {
        "type": "blockchainMembers",
        "names": ["bcm-prod-consortium", "bcm-dev-test"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.DevTestLab": {
        "type": "labs",
        "names": ["dtl-dev-sandbox", "dtl-qa-testing"],
        "principal_bias": ["User", "Group"],
    },
    "Microsoft.DataLakeAnalytics": {
        "type": "accounts",
        "names": ["dla-prod-analytics", "dla-dev-explore"],
        "principal_bias": ["User", "ServicePrincipal"],
    },
    "Microsoft.Databox": {
        "type": "jobs",
        "names": ["databox-migration-001", "databox-export-002"],
        "principal_bias": ["User"],
    },
    "Microsoft.AzureStack": {
        "type": "registrations",
        "names": ["azs-hybrid-reg", "azs-edge-001"],
        "principal_bias": ["ServicePrincipal"],
    },
    "Microsoft.Billing": {
        "type": None,
        "names": None,
        "principal_bias": ["User", "Group"],
    },
    "Microsoft.CostManagement": {
        "type": None,
        "names": None,
        "principal_bias": ["User", "Group"],
    },
    "Microsoft.Consumption": {
        "type": None,
        "names": None,
        "principal_bias": ["User", "Group"],
    },
}


def generate_principals():
    """Generate realistic Azure AD principals."""
    principals = {
        "User": [],
        "ServicePrincipal": [],
        "Group": [],
    }

    user_data = [
        ("Alice", "Johnson"),
        ("Bob", "Smith"),
        ("Carol", "Williams"),
        ("David", "Brown"),
        ("Emma", "Davis"),
        ("Frank", "Miller"),
        ("Grace", "Lee"),
    ]
    for first, last in user_data:
        principals["User"].append({
            "id": str(uuid.uuid4()),
            "type": "User",
            "displayName": f"{first} {last}",
            "userPrincipalName": f"{first.lower()}.{last.lower()}@contoso.onmicrosoft.com",
        })

    sp_data = [
        "sp-github-actions-deploy",
        "sp-terraform-automation",
        "sp-monitoring-agent",
        "sp-backup-service",
        "sp-container-registry-push",
        "sp-aks-cluster-admin",
        "sp-data-pipeline",
        "sp-key-vault-reader",
    ]
    for app_name in sp_data:
        principals["ServicePrincipal"].append({
            "id": str(uuid.uuid4()),
            "type": "ServicePrincipal",
            "displayName": app_name,
            "appId": str(uuid.uuid4()),
        })

    mi_data = ["mi-aks-prod-cluster", "mi-webapp-prod-api", "mi-function-processor"]
    for mi_name in mi_data:
        principals["ServicePrincipal"].append({
            "id": str(uuid.uuid4()),
            "type": "ServicePrincipal",
            "displayName": mi_name,
        })

    group_data = [
        "grp-platform-engineers",
        "grp-devops-admins",
        "grp-security-readers",
        "grp-developers",
        "grp-data-analysts",
    ]
    for group_name in group_data:
        principals["Group"].append({
            "id": str(uuid.uuid4()),
            "type": "Group",
            "displayName": group_name,
        })

    return principals


def extract_providers_from_role(role: dict) -> list[str]:
    """Extract resource providers from role's actions."""
    # Handle flatten.json structure (Actions/DataActions) and built-in-roles.json structure (permissions)
    if 'Actions' in role:
        # flatten.json structure
        actions = role.get('Actions', [])
        data_actions = role.get('DataActions', [])
    else:
        # built-in-roles.json structure
        actions = role.get('permissions', [{}])[0].get('actions', [])
        data_actions = role.get('permissions', [{}])[0].get('dataActions', [])

    all_actions = actions + data_actions

    providers = set()
    for action in all_actions:
        if '/' in action and not action.startswith('*'):
            provider = action.split('/')[0]
            if provider.startswith('Microsoft.'):
                providers.add(provider)

    return list(providers) if providers else ["Microsoft.Resources"]


def generate_scope_for_role(role: dict, sub: dict, rg: str) -> tuple[str, dict]:
    """Generate appropriate scope based on role's permissions."""
    providers = extract_providers_from_role(role)
    # Handle both flatten.json (RoleName) and built-in-roles.json (name)
    role_name = role.get('RoleName', role.get('name', ''))

    sub_level_keywords = ["Billing", "Cost Management", "Contributor", "Owner", "Reader"]
    is_sub_level = any(kw in role_name for kw in sub_level_keywords)

    resource_mapping = None
    for provider in providers:
        if provider in RESOURCE_MAPPINGS:
            resource_mapping = RESOURCE_MAPPINGS[provider].copy()
            resource_mapping["provider"] = provider
            break

    if resource_mapping is None:
        resource_mapping = {"type": None, "names": None, "principal_bias": ["User", "Group"], "provider": "Microsoft.Resources"}

    if is_sub_level or resource_mapping["type"] is None:
        scope_weights = [0.7, 0.3, 0.0]
    elif "Reader" in role_name:
        scope_weights = [0.2, 0.5, 0.3]
    else:
        scope_weights = [0.1, 0.3, 0.6]

    scope_type = random.choices(['subscription', 'resourceGroup', 'resource'], weights=scope_weights)[0]

    if scope_type == 'subscription':
        scope = f"/subscriptions/{sub['id']}"
    elif scope_type == 'resourceGroup':
        scope = f"/subscriptions/{sub['id']}/resourceGroups/{rg}"
    else:
        resource_name = random.choice(resource_mapping["names"]) if resource_mapping["names"] else None
        if resource_name and resource_mapping["type"]:
            scope = f"/subscriptions/{sub['id']}/resourceGroups/{rg}/providers/{resource_mapping['provider']}/{resource_mapping['type']}/{resource_name}"
        else:
            scope = f"/subscriptions/{sub['id']}/resourceGroups/{rg}"

    return scope, resource_mapping


def generate_single_assignment(role: dict, principals: dict) -> dict:
    """Generate a single assignment for a role."""
    sub = random.choice(SUBSCRIPTIONS)
    rg = random.choice(RESOURCE_GROUPS)
    scope, resource_mapping = generate_scope_for_role(role, sub, rg)

    principal_bias = resource_mapping.get("principal_bias", ["User", "Group", "ServicePrincipal"])
    principal_type = random.choice(principal_bias)
    if principal_type not in principals or not principals[principal_type]:
        principal_type = random.choice(list(principals.keys()))

    principal = random.choice(principals[principal_type])

    # Use 'Name' (GUID) from flatten.json, not 'name' (role name) from built-in-roles.json
    role_guid = role.get('Name', role.get('name'))

    return {
        "scope": scope,
        "properties": {
            "roleDefinitionId": f"/subscriptions/{sub['id']}/providers/Microsoft.Authorization/roleDefinitions/{role_guid}",
            "principalId": principal['id']
        }
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python synthesize_azure_assignments.py <roles_file.json> <num_files>")
        print("Example: python synthesize_azure_assignments.py azure_roles.json 20")
        sys.exit(1)

    roles_file = sys.argv[1]
    num_files = int(sys.argv[2])

    with open(roles_file) as f:
        roles = json.load(f)

    if isinstance(roles, dict) and 'roles' in roles:
        roles = roles['roles']

    original_count = len(roles)

    def has_permissions(role):
        if 'Actions' in role:
            actions = role.get('Actions', [])
            data_actions = role.get('DataActions', [])
        else:
            raw_perms = role.get('rawPermissions', [{}])[0]
            actions = raw_perms.get('actions', [])
            data_actions = raw_perms.get('dataActions', [])
        return len(actions) > 0 or len(data_actions) > 0

    roles = [r for r in roles if has_permissions(r)]

    filtered_count = original_count - len(roles)
    if filtered_count > 0:
        print(f"Filtered out {filtered_count} roles without permissions")

    print(f"Loaded {len(roles)} valid role definitions")
    print(f"Generating {num_files} assignment files (1 assignment per file)...")

    principals = generate_principals()

    output_dir = "assignments_output"
    os.makedirs(output_dir, exist_ok=True)

    for i in range(num_files):
        role = roles[i % len(roles)]
        assignment = generate_single_assignment(role, principals)

        # Use simple naming: as0.json, as1.json, as2.json, etc.
        filename = f"{output_dir}/as{i}.json"

        with open(filename, 'w') as f:
            json.dump([assignment], f, indent=2)

        print(f"  [{i+1}/{num_files}] {filename} -> {role.get('RoleName', role.get('name'))}")

    print(f"\nGenerated {num_files} files in '{output_dir}/'")


if __name__ == "__main__":
    main()