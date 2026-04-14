#!/bin/bash
set -e

# Log startup script output
exec > /var/log/startup-script.log 2>&1

echo "=== Starting startup script ==="

# Update system packages
apt-get update -y
apt-get upgrade -y

# Ensure gcloud CLI is installed and up to date
# (Ubuntu GCE images typically have it pre-installed, but let's make sure)
if ! command -v gcloud &> /dev/null; then
    echo "Installing Google Cloud SDK..."
    apt-get install -y apt-transport-https ca-certificates gnupg curl
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | tee /etc/apt/sources.list.d/google-cloud-sdk.list
    apt-get update -y
    apt-get install -y google-cloud-cli
else
    echo "gcloud already installed, updating..."
    apt-get install -y --only-upgrade google-cloud-cli || true
fi

echo "gcloud version:"
gcloud version

# Install Node.js (required for Cline)
echo "Installing Node.js..."
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

echo "Node.js version:"
node --version
echo "npm version:"
npm --version

# Install Cline CLI globally
echo "Installing Cline CLI..."
npm install -g @anthropic-ai/cline

echo "Cline version:"
cline --version || echo "Cline installed (version check may require config)"

echo "=== Startup script completed ==="
