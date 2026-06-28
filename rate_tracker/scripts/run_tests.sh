#!/bin/bash
# scripts/run_tests.sh — Run all tests inside Docker or locally
set -e

echo "================================"
echo "Running Rate-Tracker Test Suite"
echo "================================"

pytest -v --tb=short --cov=rates --cov-report=term-missing

echo ""
echo "================================"
echo "All tests passed!"
echo "================================"
