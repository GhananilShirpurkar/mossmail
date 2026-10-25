"""Scores are advisory. Hard safety rules always run independently of a scorer."""

from typing import Protocol

from .models import Message, Score
from .policy import risk_evidence


class Scorer(Protocol):
    def score(self, message: Message) -> Score: ...


class BaselineScorer:
    def score(self, message: Message) -> Score:
        evidence = risk_evidence(message)
        risk = 0.9 if evidence else (0.12 if message.trusted_bulk else 0.45)
        uncertainty = 0.1 if message.trusted_bulk or evidence else 0.55
        if message.parse_uncertain or message.has_attachments or not message.body.strip():
            uncertainty = 0.85
            evidence.append("Content is incomplete, attachment-dependent, or uncertain.")
        if message.trusted_bulk:
            evidence.append("Locally curated bulk subscription; no reply history is used.")
        if not evidence:
            evidence.append("No reliable low-risk evidence; absence of a keyword is not safety.")
        return Score(
            risk=risk, uncertainty=uncertainty, method="Transparent baseline", evidence=evidence
        )


FEATURE_NAMES = ("body_length", "recipient_count", "question_count", "attachment", "risk_signals")


def feature_row(message: Message) -> list[float]:
    # Never include content, sender, subject, addresses or identifiers in hosted features.
    return [
        min(len(message.body), 10000),
        len(message.recipients),
        min(message.body.count("?"), 20),
        int(message.has_attachments),
        len(risk_evidence(message)),
    ]


class HostedTabPFNScorer:
    """Optional real SDK adapter. Fit on human risk labels, never reply/non-reply labels.

    Calling fit/predict sends numeric feature data to Prior Labs. Not auto-enabled.
    Training/evaluation/generalization are the operator's responsibility.
    """

    def __init__(self, *, consent: bool, classifier=None):
        if not consent:
            raise PermissionError("Explicit consent required: features are sent to Prior Labs")
        if classifier is None:
            from tabpfn_client import TabPFNClassifier

            classifier = TabPFNClassifier()
        self.classifier = classifier
        self.fitted = False

    def fit(self, rows: list[list[float]], labels: list[int]) -> "HostedTabPFNScorer":
        import numpy as np

        x = np.asarray(rows, dtype=float)
        if x.ndim != 2 or x.shape[1] != len(FEATURE_NAMES) or not np.isfinite(x).all():
            raise ValueError("Expected finite numeric feature rows in documented column order")
        if len(rows) != len(labels) or set(labels) != {0, 1}:
            raise ValueError("Require both human-labeled risk classes, 0 and 1")
        self.classifier.fit(x, np.asarray(labels))
        self.fitted = True
        return self

    def score(self, message: Message) -> Score:
        import numpy as np

        if not self.fitted:
            raise RuntimeError("Fit on consented, human-labeled risk examples first")
        probabilities = self.classifier.predict_proba(np.asarray([feature_row(message)]))
        positive = list(self.classifier.classes_).index(1)
        return Score(
            risk=float(probabilities[0][positive]),
            # Until calibrated on representative data, predictions cannot authorize parking.
            uncertainty=0.6,
            method="Hosted TabPFN (uncalibrated)",
            evidence=["Hosted numeric-feature risk estimate; no validation claim."],
        )
