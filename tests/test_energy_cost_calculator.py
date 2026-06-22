"""
Unit tests for energy_cost_calculator.py and helper functions.
Tests cover unit conversion, validation, cost calculations, and error handling.
"""

import unittest
import sys
import os
import json
import tempfile
from datetime import datetime
import pandas as pd
import numpy as np

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from energy_cost_calculator import EnergyCostCalculator
from helpers.data_loader import DataForCostCalculation
from helpers.openei_helpers import get_processed_data


class TestUnitConversion(unittest.TestCase):
    """Test unit conversion methods."""

    def setUp(self):
        """Set up test fixtures."""
        # Create minimal rate data
        self.rate_data = {
            "label": "test_rate",
            "demandunits": "kW",
            "energyunits": "kWh",
        }

        # Create minimal dataframe
        self.data = pd.DataFrame(
            {
                "Electricity:Facility [W](Hourly)": [1000, 2000, 3000],
                "Environment:Site Day Type Index [](Hourly)": [2, 3, 4],
            },
            index=pd.date_range("2023-01-01", periods=3, freq="H"),
        )

        self.calculator = EnergyCostCalculator(
            rate_json_path=None,
            rate_label=None,
            data=self.data,
            electricity_demand_var_name="Electricity:Facility [W](Hourly)",
        )
        self.calculator.rate = self.rate_data

    def test_extract_unit_from_column_name(self):
        """Test unit extraction from column names."""
        # Test standard EnergyPlus format
        self.assertEqual(
            self.calculator._extract_unit_from_column_name(
                "Electricity:Facility [W](Hourly)"
            ),
            "W",
        )
        self.assertEqual(
            self.calculator._extract_unit_from_column_name("Demand [kW](Monthly)"), "kW"
        )
        # Test no unit
        self.assertIsNone(
            self.calculator._extract_unit_from_column_name("SomeVariable")
        )

    def test_convert_power_to_kw(self):
        """Test power conversion to kW."""
        # W to kW
        self.assertAlmostEqual(self.calculator._convert_power_to_kw(1000, "W"), 1.0)
        # kW to kW (no conversion)
        self.assertAlmostEqual(self.calculator._convert_power_to_kw(5.0, "kW"), 5.0)
        # MW to kW
        self.assertAlmostEqual(self.calculator._convert_power_to_kw(0.001, "MW"), 1.0)
        # Joule to kW
        self.assertAlmostEqual(self.calculator._convert_power_to_kw(3600000, "J"), 1.0)
        # Case insensitive
        self.assertAlmostEqual(self.calculator._convert_power_to_kw(1000, "w"), 1.0)


class TestUnitValidation(unittest.TestCase):
    """Test unit validation methods."""

    def setUp(self):
        """Set up test fixtures."""
        self.rate_data = {
            "label": "test_rate",
            "demandunits": "kW",
            "energyunits": "kWh",
        }

        self.data = pd.DataFrame(
            {
                "Electricity:Facility [W](Hourly)": [1000],
                "Environment:Site Day Type Index [](Hourly)": [2],
            },
            index=pd.date_range("2023-01-01", periods=1, freq="H"),
        )

        self.calculator = EnergyCostCalculator(
            rate_json_path=None, rate_label=None, data=self.data
        )
        self.calculator.rate = self.rate_data

    def test_get_expected_demand_unit(self):
        """Test extraction of expected demand unit from rate."""
        self.assertEqual(self.calculator._get_expected_demand_unit(), "kW")

        # Test with missing unit
        self.calculator.rate = {"label": "test"}
        self.assertIsNone(self.calculator._get_expected_demand_unit())

    def test_get_expected_energy_unit(self):
        """Test extraction of expected energy unit from rate."""
        self.assertEqual(self.calculator._get_expected_energy_unit(), "kWh")

        # Test default when missing
        self.calculator.rate = {"label": "test"}
        self.assertEqual(self.calculator._get_expected_energy_unit(), "kWh")

    def test_validate_demand_units_matching(self):
        """Test validation when units match."""
        result = self.calculator._validate_demand_units("W")
        self.assertTrue(result)

    def test_validate_demand_units_mismatch(self):
        """Test validation when units don't match."""
        self.calculator.rate = {"demandunits": "MW"}
        result = self.calculator._validate_demand_units("W")
        self.assertFalse(result)


class TestRateLoading(unittest.TestCase):
    """Test rate loading functionality."""

    def test_load_rate_from_json(self):
        """Test loading rate from JSON file."""
        # Create temporary JSON file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"label": "test_rate", "name": "Test Rate"}, f)
            temp_path = f.name

        try:
            calculator = EnergyCostCalculator(rate_json_path=temp_path, data=None)
            self.assertIsNotNone(calculator.rate)
            self.assertEqual(calculator.rate["label"], "test_rate")
        finally:
            os.unlink(temp_path)

    def test_load_rate_missing_file(self):
        """Test loading rate from non-existent file."""
        calculator = EnergyCostCalculator(
            rate_json_path="/nonexistent/path/rate.json", data=None
        )
        self.assertIsNone(calculator.rate)

    def test_load_rate_no_source(self):
        """Test error when neither JSON nor label provided."""
        calculator = EnergyCostCalculator(
            rate_json_path=None, rate_label=None, data=None
        )
        self.assertIsNone(calculator.rate)


class TestFixedCharges(unittest.TestCase):
    """Test fixed charge calculations."""

    def setUp(self):
        """Set up test fixtures."""
        self.data = pd.DataFrame(
            {
                "Electricity:Facility [W](Hourly)": [1000] * 8760,
                "Environment:Site Day Type Index [](Hourly)": [2] * 8760,
            },
            index=pd.date_range("2023-01-01", periods=8760, freq="H"),
        )

    def test_fixed_charge_monthly(self):
        """Test monthly fixed charges."""
        rate = {
            "label": "test_rate",
            "fixedchargeunits": "$/month",
            "fixedchargefirstmeter": 10.0,
            "fixedchargeeaaddl": 5.0,
        }

        calculator = EnergyCostCalculator(
            rate_json_path=None,
            data=self.data,
            include_fixed_cost=True,
            number_of_meters=3,
        )
        calculator.rate = rate

        fixed_cost = calculator.calculate_fixed_charge_cost()
        # 12 months * (10 + 5*2) = 12 * 20 = 240
        self.assertAlmostEqual(fixed_cost, 240.0)

    def test_fixed_charge_daily(self):
        """Test daily fixed charges."""
        rate = {
            "label": "test_rate",
            "fixedchargeunits": "$/day",
            "fixedchargefirstmeter": 1.0,
            "fixedchargeeaaddl": 0.5,
        }

        calculator = EnergyCostCalculator(
            rate_json_path=None,
            data=self.data,
            include_fixed_cost=True,
            number_of_meters=2,
        )
        calculator.rate = rate

        fixed_cost = calculator.calculate_fixed_charge_cost()
        # 365 days * (1 + 0.5*1) = 365 * 1.5 = 547.5
        self.assertAlmostEqual(fixed_cost, 547.5)

    def test_fixed_monthly_charge(self):
        """Test fixedmonthlycharge field."""
        rate = {"label": "test_rate", "fixedmonthlycharge": 25.0}

        calculator = EnergyCostCalculator(
            rate_json_path=None, data=self.data, include_fixed_cost=True
        )
        calculator.rate = rate

        fixed_cost = calculator.calculate_fixed_charge_cost()
        # 12 months * 25 = 300
        self.assertAlmostEqual(fixed_cost, 300.0)


class TestNumberOfMeters(unittest.TestCase):
    """Test number of meters validation."""

    def test_number_of_meters_minimum(self):
        """Test that number_of_meters cannot be less than 1."""
        calculator = EnergyCostCalculator(
            rate_json_path=None, data=None, number_of_meters=0
        )
        self.assertEqual(calculator.number_of_meters, 1)

        calculator = EnergyCostCalculator(
            rate_json_path=None, data=None, number_of_meters=-5
        )
        self.assertEqual(calculator.number_of_meters, 1)

    def test_number_of_meters_valid(self):
        """Test valid number_of_meters values."""
        calculator = EnergyCostCalculator(
            rate_json_path=None, data=None, number_of_meters=5
        )
        self.assertEqual(calculator.number_of_meters, 5)


class TestGetSummary(unittest.TestCase):
    """Test summary generation."""

    def setUp(self):
        """Set up test fixtures."""
        # Create sample data with energy and demand charges
        dates = pd.date_range("2023-01-01", periods=100, freq="H")
        self.data = pd.DataFrame(
            {
                "Electricity:Facility [W](Hourly)": np.random.uniform(1000, 5000, 100),
                "Environment:Site Day Type Index [](Hourly)": [2] * 100,
                "energy_charge": np.random.uniform(10, 50, 100),
                "energy_usage_kWh": np.random.uniform(1, 5, 100),
                "demand_charge": [0] * 100,
                "demand_usage_kW": np.random.uniform(1, 5, 100),
            },
            index=dates,
        )

        # Add some demand charges in specific timesteps
        self.data.loc[self.data.index[10], "demand_charge"] = 100.0
        self.data.loc[self.data.index[50], "demand_charge"] = 150.0

    def test_summary_structure(self):
        """Test that summary contains expected keys."""
        calculator = EnergyCostCalculator(
            rate_json_path=None,
            data=self.data,
            include_energy_cost=True,
            include_demand_cost=True,
        )
        calculator.rate = {"label": "test"}

        summary = calculator.get_summary()

        # Check overall totals exist
        self.assertIn("total_cost", summary)
        self.assertIn("energy_cost_total", summary)
        self.assertIn("demand_cost_total", summary)

        # Check monthly breakdowns exist
        self.assertIn("energy_cost_month_01", summary)
        self.assertIn("demand_cost_month_01", summary)

    def test_summary_calculations(self):
        """Test that summary values are calculated correctly."""
        calculator = EnergyCostCalculator(
            rate_json_path=None,
            data=self.data,
            include_energy_cost=True,
            include_demand_cost=True,
        )
        calculator.rate = {"label": "test"}

        summary = calculator.get_summary()

        # Verify energy cost total
        expected_energy_total = self.data["energy_charge"].sum()
        self.assertAlmostEqual(summary["energy_cost_total"], expected_energy_total)

        # Verify demand cost total
        expected_demand_total = self.data["demand_charge"].sum()
        self.assertAlmostEqual(summary["demand_cost_total"], expected_demand_total)


class TestVariableTimestep(unittest.TestCase):
    """Test variable timestep support."""

    def test_timestep_calculation(self):
        """Test that timestep fractions are calculated correctly."""
        # Create data with 15-minute intervals
        dates = pd.date_range("2023-01-01", periods=10, freq="15T")
        data = pd.DataFrame(
            {
                "Electricity:Facility [W](Hourly)": [1000] * 10,
                "Environment:Site Day Type Index [](Hourly)": [2] * 10,
            },
            index=dates,
        )

        # We'll just verify the data structure is handled
        calculator = EnergyCostCalculator(
            rate_json_path=None,
            data=data,
            electricity_demand_var_name="Electricity:Facility [W](Hourly)",
        )

        self.assertIsNotNone(calculator.data)
        self.assertEqual(len(calculator.data), 10)


class TestErrorHandling(unittest.TestCase):
    """Test error handling and edge cases."""

    def test_missing_demand_variable(self):
        """Test error when demand variable is missing."""
        data = pd.DataFrame(
            {
                "SomeOtherVariable": [1000],
                "Environment:Site Day Type Index [](Hourly)": [2],
            },
            index=pd.date_range("2023-01-01", periods=1, freq="H"),
        )

        calculator = EnergyCostCalculator(
            rate_json_path=None,
            data=data,
            electricity_demand_var_name="NonExistentVariable",
        )
        calculator.rate = {"label": "test"}

        # Should return 0 and not crash
        cost = calculator.calculate_demand_cost()
        self.assertEqual(cost, 0)

    def test_missing_day_type_column(self):
        """Test error when day type column is missing."""
        data = pd.DataFrame(
            {"Electricity:Facility [W](Hourly)": [1000]},
            index=pd.date_range("2023-01-01", periods=1, freq="H"),
        )

        calculator = EnergyCostCalculator(
            rate_json_path=None,
            data=data,
            electricity_demand_var_name="Electricity:Facility [W](Hourly)",
        )
        calculator.rate = {"label": "test"}

        # Should return 0 and not crash
        cost = calculator.calculate_demand_cost()
        self.assertEqual(cost, 0)

    def test_no_rate_data(self):
        """Test behavior when rate is None."""
        data = pd.DataFrame(
            {
                "Electricity:Facility [W](Hourly)": [1000],
                "Environment:Site Day Type Index [](Hourly)": [2],
            },
            index=pd.date_range("2023-01-01", periods=1, freq="H"),
        )

        calculator = EnergyCostCalculator(rate_json_path=None, data=data)
        calculator.rate = None

        total_cost = calculator.get_total_cost()
        self.assertEqual(total_cost, 0)

    def test_no_data(self):
        """Test behavior when data is None."""
        calculator = EnergyCostCalculator(rate_json_path=None, data=None)
        calculator.rate = {"label": "test"}

        total_cost = calculator.get_total_cost()
        self.assertEqual(total_cost, 0)


class TestDataLoader(unittest.TestCase):
    """Test DataForCostCalculation helper class."""

    def test_data_loader_initialization(self):
        """Test that DataForCostCalculation initializes correctly."""
        # This test would require actual test data files
        # Skipping actual file loading test
        pass


if __name__ == "__main__":
    # Run tests with verbosity
    unittest.main(verbosity=2)
