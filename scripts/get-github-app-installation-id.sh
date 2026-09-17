#!/bin/bash
# Get GitHub App Installation ID

echo "Getting GitHub App Installation ID..."
echo ""
echo "Option 1: From GitHub UI (easiest)"
echo "Go to: https://github.com/settings/installations"
echo "Click on your 'ShipZen' app"
echo "The URL will look like: https://github.com/settings/installations/12345678"
echo "The number at the end (12345678) is your Installation ID"
echo ""
echo "Option 2: From GitHub API"
echo "You need to create a JWT first (complex)"
echo ""
echo "Once you have it, add it to GitHub Secrets as: GITHUB_APP_INSTALLATION_ID"
