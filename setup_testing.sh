#!/bin/bash
# Quick setup script for testing

echo "Setting up testing for Movie Analytics Dashboard..."

# Install testing dependencies
echo "Installing testing dependencies..."
pip install pytest pytest-flask pytest-cov coverage

# Install optional tools
echo "Installing optional testing tools..."
pip install pytest-xdist  # For parallel testing
pip install pre-commit    # For pre-commit hooks

# Setup pre-commit hooks (optional)
read -p "Do you want to install pre-commit hooks? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]
then
    pre-commit install
    echo "Pre-commit hooks installed!"
fi

# Run tests
echo ""
echo "Running tests..."
pytest -v --cov=src --cov-report=term-missing

echo ""
echo "Testing setup complete!"
echo ""
echo "Common commands:"
echo "  pytest                    # Run all tests"
echo "  pytest -v                 # Verbose output"
echo "  pytest --cov=src          # With coverage"
echo "  pytest -x                 # Stop on first failure"
echo "  pytest tests/test_routes.py  # Run specific file"
echo ""
echo "See TESTING.md for more information!"
