name: NTRIP Stream Monitor

on:
  schedule:
    # Runs automatically every 6 hours
    - cron: '0 */6 * * *'
  # Allows you to trigger the monitor manually from the Actions tab anytime
  workflow_dispatch:

jobs:
  run-monitor:
    runs-on: ubuntu-latest

    permissions:
      contents: write # Grants GitHub Actions permission to commit files back to your repo

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/python-spec@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install matplotlib

      - name: Run NTRIP Stream Monitor (30-Minute Sampling Session)
        run: |
          # Runs the python logger for 30 minutes (1800 seconds) per job run
          timeout 1800s python ntrip_headless_logger.py || true

      - name: Commit and push updated logs & graph
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action Bot"
          git add ntrip_reliability_log.csv ntrip_session_summary.png
          git commit -m "Auto-update NTRIP log and summary graph [skip ci]" || echo "No changes to commit"
          git push
