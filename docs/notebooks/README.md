# Reproducible DS Notebooks

These notebooks are designed for reproducible storytelling over production telemetry snapshots:

- `analytics_warehouse_story.ipynb`:
  - reads analytics warehouse aggregates (`daily`, `funnel`, `cohort`)
  - reads feature-store labels
  - renders reproducible charts and summary tables

## Usage

1. Rebuild warehouse snapshots:
   ```bash
   python backend/scripts/rebuild_analytics_warehouse.py --lookback-days 30 --traffic-type real
   ```
2. Start Jupyter from repo root:
   ```bash
   python -m jupyter lab
   ```
3. Open `docs/notebooks/analytics_warehouse_story.ipynb` and run all cells.

## Determinism Notes

- Notebook reads from persisted aggregate collections, not ad-hoc raw-event scans.
- Date windows and filters are explicit in parameters cell.
- Plot inputs are tables that can be exported directly for portfolio reporting.
