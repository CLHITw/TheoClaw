import pytest

from theoclaw.evals.report import pass_at_k, pass_hat_k, run_cost


def test_k_equals_n_is_any_and_all():
    assert pass_at_k(5, 1, 5) == 1.0 and pass_at_k(5, 0, 5) == 0.0
    assert pass_hat_k(5, 5, 5) == 1.0 and pass_hat_k(5, 4, 5) == 0.0


def test_k1_is_pass_rate():
    assert pass_at_k(5, 3, 1) == pytest.approx(0.6)
    assert pass_hat_k(5, 3, 1) == pytest.approx(0.6)


def test_estimator_values():
    # 5 runs, 3 passes, k=2: P(at least one of 2 passes) = 1 - C(2,2)/C(5,2) = 0.9
    assert pass_at_k(5, 3, 2) == pytest.approx(0.9)
    # P(both pass) = C(3,2)/C(5,2) = 0.3
    assert pass_hat_k(5, 3, 2) == pytest.approx(0.3)


def test_cost():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 1_000_000}
    assert run_cost(usage, "claude-opus-5-5") == pytest.approx(4.0 + 2.0 + 0.2)
    assert run_cost(usage, "fake-honest") is None
