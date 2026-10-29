from analytics import Analytics
from pathlib import Path

# report generation entrypoint
# requires already shelved analytics
# which means crawler has already been run
# read stopwords without importing scraper
with Path("stopwords.txt").open("r") as f:
    stopwords = [line.strip() for line in f if line.strip()]
analytics = Analytics(stopwords)

try:
    analytics.generate_report()
    analytics.generate_diagnostics()
finally:
    analytics.close()