# Portfolio / ATS Bundle

This folder contains publish-ready evidence artifacts for DS + AI/ML + Fullstack evaluation.

## Contents

- `architecture.md`: architecture narrative + system flow.
- `ablation_table.md`: benchmark + lifecycle ablation summary.
- `screenshot_pack.md`: screenshot index for dashboard evidence.
- `screenshots/`: generated dashboard images (PNG).

## Generate / Refresh

1. Recompute benchmark + lifecycle assets:
   ```bash
   ./scripts/reproduce_results.sh
   ```
2. Publish ablation markdown from the latest benchmark files:
   ```bash
   python backend/scripts/publish_portfolio_bundle.py
   ```
3. Capture screenshot pack (after frontend is running on Slim):
   ```bash
   ./scripts/capture_dashboard_screenshots.sh
   ```
