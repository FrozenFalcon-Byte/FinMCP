"""Canonical category names, and how forgiving the mapping onto them is."""
from finmcp.taxonomy import resolve_category_name


def test_resolve_strips_decoration_a_model_copied_from_the_prompt():
    """A smaller model answers with the whole list line, not the name: "Other (expense)" is still Other."""
    assert resolve_category_name("Other (expense)") == "Other"
    assert resolve_category_name("Food & Dining: eating out and takeaway") == "Food & Dining"
    assert resolve_category_name("Transport — getting around") == "Transport"
    assert resolve_category_name("Groceries  [expense]") == "Groceries"
    assert resolve_category_name("Loans & EMI") == "Loans & EMI"  # a real name survives untouched
    assert resolve_category_name("not a category at all") is None
