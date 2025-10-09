#!/bin/bash
set -e  # Exit immediately if a command fails

echo "Setting up FieldImage..."

# Create virtual environment
python3 -m venv .venv || {
  echo
  echo "❌ ERROR: Failed to create virtual environment."
  exit 1
}

source .venv/bin/activate || {
  echo
  echo "❌ ERROR: Failed to activate virtual environment."
  exit 1
}

# Upgrade pip
python -m pip install --upgrade pip || {
  echo
  echo "❌ ERROR: Failed to upgrade pip."
  echo "➡️ Check your internet connection or try again later."
  exit 1
}

# Install the package
pip install . || {
  echo
  echo "❌ ERROR: pip install failed."
  echo "➡️ Please review the error above and ensure dependencies are met."
  exit 1
}

echo "Setup complete! Virtual environment is now active."
echo "You can start using FieldImage inside this environment."