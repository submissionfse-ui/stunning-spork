# Usage:
#   Single policy:  ./run_quacky_azure.sh <role_definitions> <assignment1>
#   Two policies:   ./run_quacky_azure.sh <role_definitions> <assignment1> <assignment2>
#
# Examples:
#   ./run_quacky_azure.sh roles.json assignment1.json
#   ./run_quacky_azure.sh roles.json assignment1.json assignment2.json

ROLE_DEFS="$1"
ASSIGNMENT1="$2"
ASSIGNMENT2="$3"

BOUND=100
MODELS=50
MIN_RANGE=20
MAX_RANGE=100

if [ -z "$ROLE_DEFS" ] || [ -z "$ASSIGNMENT1" ]; then
    echo "Usage:"
    echo "  Single policy:  $0 <role_definitions> <assignment1>"
    echo "  Two policies:   $0 <role_definitions> <assignment1> <assignment2>"
    exit 1
fi

if [ -z "$ASSIGNMENT2" ]; then
    # Single policy
    echo "Running single policy analysis..."
    echo "  Role Definitions: $ROLE_DEFS"
    echo "  Assignment: $ASSIGNMENT1"
    echo ""
    
    python3 quacky.py \
        -rd "$ROLE_DEFS" \
        -ra1 "$ASSIGNMENT1" \
        -b "$BOUND" \
        -m "$MODELS" \
        -m1 "$MIN_RANGE" \
        -m2 "$MAX_RANGE" \
        -pr
else
    # Two policies
    echo "Running two policy comparison..."
    echo "  Role Definitions: $ROLE_DEFS"
    echo "  Assignment 1: $ASSIGNMENT1"
    echo "  Assignment 2: $ASSIGNMENT2"
    echo ""
    
    python3 quacky.py \
        -rd "$ROLE_DEFS" \
        -ra1 "$ASSIGNMENT1" \
        -ra2 "$ASSIGNMENT2" \
        -b "$BOUND" \
        -m "$MODELS" \
        -m1 "$MIN_RANGE" \
        -m2 "$MAX_RANGE" \
        -pr
fi