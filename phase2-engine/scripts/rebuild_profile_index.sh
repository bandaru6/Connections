#!/bin/bash
set -e

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_ROOT/.venv_phase2_py311/bin/python"
INDEX_SCRIPT="$SCRIPT_DIR/build_profile_index.py"

echo "=== Rebuilding Profile Index ==="
echo "Using Python: $VENV_PYTHON"
echo "Script: $INDEX_SCRIPT"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment python not found at $VENV_PYTHON"
    exit 1
fi

"$VENV_PYTHON" "$INDEX_SCRIPT"

if [ $? -eq 0 ]; then
    echo "=== Success ==="
    echo "Artifacts written to $PROJECT_ROOT/artifacts/"
else
    echo "=== Failure ==="
    echo "Index build failed."
    exit 1
fi
