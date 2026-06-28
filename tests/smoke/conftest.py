"""Configuration exclusive to the smoke suite.

These tests are independent of the main suite (unit + integration).
Run them by pointing directly at this directory:

    uv run pytest tests/smoke/ -v -s

They do not require --run-integration or any additional environment
variables, but they do need an internet connection and Playwright installed.
"""
