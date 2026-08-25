from src.codepilot.test_agent.runner import run_test_suite


def test_run_test_suite_passing(tmp_path):
    (tmp_path / "test_ok.py").write_text(
        "def test_addition():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )

    result = run_test_suite(tmp_path)

    assert result.passed is True
    assert result.no_tests_collected is False
    assert result.exit_code == 0
    assert result.counts.get("passed") == 1
    assert result.failure_summary == []


def test_run_test_suite_failing(tmp_path):
    (tmp_path / "test_broken.py").write_text(
        "def test_addition():\n    assert 1 + 1 == 3\n", encoding="utf-8"
    )

    result = run_test_suite(tmp_path)

    assert result.passed is False
    assert result.no_tests_collected is False
    assert result.exit_code == 1
    assert result.counts.get("failed") == 1
    assert any("test_broken.py" in line for line in result.failure_summary)


def test_run_test_suite_no_tests_collected(tmp_path):
    (tmp_path / "not_a_test.py").write_text("x = 1\n", encoding="utf-8")

    result = run_test_suite(tmp_path)

    assert result.no_tests_collected is True
    assert result.exit_code == 5
    assert result.passed is False


def test_run_test_suite_mixed_pass_and_fail(tmp_path):
    (tmp_path / "test_mixed.py").write_text(
        "def test_pass():\n    assert True\n\n\ndef test_fail():\n    assert False\n",
        encoding="utf-8",
    )

    result = run_test_suite(tmp_path)

    assert result.passed is False
    assert result.counts.get("passed") == 1
    assert result.counts.get("failed") == 1
