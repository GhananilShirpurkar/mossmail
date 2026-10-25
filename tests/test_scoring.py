import numpy as np
import pytest

from mossmail.models import State
from mossmail.scoring import HostedTabPFNScorer, feature_row


def test_hosted_requires_explicit_consent():
    with pytest.raises(PermissionError):
        HostedTabPFNScorer(consent=False)


def test_adapter_class_order_and_uncertainty(message):
    from mossmail.decision_engine import decide

    class FakeSDK:
        classes_ = np.array([1, 0])

        def fit(self, x, y):
            assert x.shape == (2, 5)

        def predict_proba(self, x):
            return np.array([[0.1, 0.9]])

    scorer = HostedTabPFNScorer(consent=True, classifier=FakeSDK()).fit(
        [[10, 1, 0, 0, 0], [20, 1, 1, 0, 2]], [0, 1]
    )
    assert scorer.score(message).risk == 0.1
    assert decide(message, scorer=scorer).state == State.REVIEW
    assert all(isinstance(x, (int, float)) for x in feature_row(message))
