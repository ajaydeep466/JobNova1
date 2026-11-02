#!/usr/bin/env bash
# Installs Chrome for the JavaScript fallback. Run on the VM as the ubuntu user: bash /opt/jobnova/install_browser.sh
set -euo pipefail
PY=/opt/jobnova/venv/bin
"$PY/pip" install playwright
sudo env "PATH=$PATH" "$PY/playwright" install-deps chromium
"$PY/playwright" install chromium
sudo systemctl restart jobnova
echo "Done. Test with:  /api/source-debug?key=YOUR_ADMIN_KEY&name=SSC&render=1"
free -m
