"""Unit tests for the de-identification helpers used by the research export."""

from anonymize import pseudonymize, scrub


def test_pseudonym_is_stable_and_prefixed():
    a = pseudonymize("user-123", "anon")
    assert a == pseudonymize("user-123", "anon")  # stable across calls
    assert a.startswith("anon-")
    assert a != pseudonymize("user-999", "anon")  # different inputs differ


def test_pseudonym_not_reversible_to_input():
    a = pseudonymize("user-123", "anon")
    assert "user-123" not in a


def test_scrub_redacts_known_name_and_email():
    out = scrub(
        "Hi, I'm Jane Doe and my email is jane.doe@northeastern.edu",
        known_name="Jane Doe",
        known_email="jane.doe@northeastern.edu",
    )
    assert "Jane" not in out and "Doe" not in out
    assert "@northeastern" not in out
    assert "[NAME]" in out and "[EMAIL]" in out


def test_scrub_redacts_generic_pii_without_known_terms():
    out = scrub("Call me at 617-555-1234, NUID 001234567, ssn 123-45-6789, see https://x.io/p")
    assert "617-555-1234" not in out and "[PHONE]" in out
    assert "001234567" not in out and "[ID]" in out
    assert "123-45-6789" not in out and "[SSN]" in out
    assert "https://x.io" not in out and "[URL]" in out


def test_scrub_keeps_benign_code_intact():
    code = "def add(a, b):\n    return a + b  # @brief adds"
    out = scrub(code)
    assert "def add(a, b)" in out  # no over-redaction of normal text/code


def test_scrub_handles_none_and_empty():
    assert scrub(None) is None
    assert scrub("") == ""
