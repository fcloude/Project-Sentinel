import numpy as np

from src.faces.evaluate import evaluate


def test_well_separated_people_score_perfectly_at_a_sensible_threshold():
    rng = np.random.default_rng(1)
    people = {
        "alice": [np.array([1, 0, 0]) + rng.normal(0, 0.05, 3) for _ in range(5)],
        "bob": [np.array([0, 1, 0]) + rng.normal(0, 0.05, 3) for _ in range(5)],
    }

    rows = evaluate(people, [0.5, -1.0])

    sensible, accept_everything = rows
    assert sensible["true_accept_rate"] == 1.0
    assert sensible["false_accept_rate"] == 0.0
    assert accept_everything["false_accept_rate"] == 1.0   # threshold -1 accepts all pairs
    assert sensible["genuine_pairs"] == 20 and sensible["impostor_pairs"] == 25


def test_without_enough_data_rates_are_none():
    rows = evaluate({"alice": [np.array([1.0, 0.0])]}, [0.3])
    assert rows[0]["true_accept_rate"] is None
    assert rows[0]["false_accept_rate"] is None
