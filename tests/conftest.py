import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest
from likewise import specs


SPECS = str(pathlib.Path(__file__).resolve().parents[1] / "specs")


@pytest.fixture(scope="session")
def spec():
    """The specification IN FORCE -- deliberately not a pinned version.

    A suite pinned to a historical version tests a product nobody runs. Every property
    here should hold of whatever ships, and if raising the in-force version breaks a
    test, that is the suite doing its job rather than a fixture needing an update.
    """
    return specs.load_in_force(SPECS)


@pytest.fixture(scope="session")
def spec_v1():
    """1.0.0, for the handful of tests that are ABOUT an older standard: replay
    reproducibility, and gate mutations written against that file's shape."""
    return specs.load(spec_dir=SPECS, version="1.0.0")


@pytest.fixture
def base_pair():
    exact = dict(activity_year=2025, loan_purpose=1, occupancy_type=1, lien_status=1,
                 loan_type=1, county_code="12086", aus_1=1, construction_method=1,
                 total_units=1, submission_of_application=1,
                 initially_payable_to_institution=1, conforming_loan_limit="C",
                 amortization=1, interest_only_payment=2, balloon_payment=2,
                 negative_amortization=2, has_co_applicant=0)
    a = dict(exact, record_key="A1", action_taken=1, loan_amount=270000.0, income=88000.0,
             property_value=285000.0, combined_loan_to_value_ratio=94.2,
             debt_to_income_ratio=40.0)
    d = dict(a, record_key="D1", action_taken=3, combined_loan_to_value_ratio=94.6)
    return a, d
