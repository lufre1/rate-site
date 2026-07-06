#!/bin/bash
# Test script for frontend translations
# Run from project root: ./test-translations.sh

set -e

echo "============================================================"
echo "TRANSLATION TESTS"
echo "============================================================"

FRONTEND_DIR="frontend"

# Check if translation files exist
if [ ! -f "$FRONTEND_DIR/src/translations/de.json" ]; then
    echo "✗ German translation file missing"
    exit 1
fi

if [ ! -f "$FRONTEND_DIR/src/translations/en.json" ]; then
    echo "✗ English translation file missing"
    exit 1
fi

echo "✓ Translation files exist"

# Check if translation test file exists
if [ ! -f "$FRONTEND_DIR/src/translations/translations.test.js" ]; then
    echo "✗ Translation test file missing"
    exit 1
fi

echo "✓ Translation test file exists"

# Run tests using Node.js directly
cd "$FRONTEND_DIR"

echo ""
echo "Running translation structure tests..."
npx jest translations.test.js --watchAll=false

echo ""
echo "============================================================"
echo "TRANSLATION TESTS PASSED"
echo "============================================================"