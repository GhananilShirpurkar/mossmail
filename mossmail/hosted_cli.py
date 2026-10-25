"""Explicit hosted experiment; numeric CSV only. The dashboard remains local baseline."""

import argparse
import csv
import os
from pathlib import Path

from .scoring import FEATURE_NAMES, HostedTabPFNScorer
from .storage import load_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training_csv", type=Path)
    parser.add_argument("--consent-to-hosted-features", action="store_true")
    args = parser.parse_args()
    consent = (
        args.consent_to_hosted_features and os.getenv("MOSSMAIL_ALLOW_HOSTED_FEATURES") == "true"
    )
    if not consent:
        parser.error(
            "Both explicit consent flag and MOSSMAIL_ALLOW_HOSTED_FEATURES=true are required"
        )
    with args.training_csv.open() as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != [*FEATURE_NAMES, "human_risk"]:
            parser.error("CSV must contain only documented numeric columns and human_risk")
        rows = list(reader)
    print("Sending numeric training and synthetic example features to Prior Labs.")
    scorer = HostedTabPFNScorer(consent=True).fit(
        [[float(r[k]) for k in FEATURE_NAMES] for r in rows],
        [int(r["human_risk"]) for r in rows],
    )
    for message in load_demo(Path(__file__).parents[1] / "data/demo_emails.json"):
        score = scorer.score(message)
        print(message.id, round(score.risk, 3), score.method)


if __name__ == "__main__":
    main()
