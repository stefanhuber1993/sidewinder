#!/bin/bash
set -e

# hidapi native library (required by the hid Python package on macOS)
if ! brew list hidapi &>/dev/null; then
    echo "Installing hidapi via Homebrew..."
    brew install hidapi
fi

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "Done. Run: source venv/bin/activate"
