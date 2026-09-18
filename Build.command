#!/bin/bash
cd "$(dirname "$0")"
bash build.sh
echo ""
echo "Press any key to close..."
read -n 1
