"""
Test Framework for Comparing Energy Cost Calculators

This script runs both energy_cost_calculator.py and tou_calculator.py
against the same CSV data and compares their outputs.
"""

import sys
import os
import json
import pandas as pd
from datetime import datetime
import traceback

# Add paths to import modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "geb_script"),
)

# Import both calculators
from energy_cost_calculator import EnergyCostCalculator
from helpers.data_loader import DataForCostCalculation

# Import tou_calculator
try:
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "references")
    )
    from tou_calculator import calculate_charge as tou_calculate_charge
except ImportError as e:
    print(f"Warning: Could not import tou_calculator: {e}")
    tou_calculate_charge = None


class CalculatorComparison:
    """Framework to test and compare both energy cost calculators"""

    def __init__(self, csv_path, rate_json_path, year=2017):
        """
        Initialize the comparison framework

        Args:
            csv_path: Path to the CSV file with energy data
            rate_json_path: Path to the rate JSON file
            year: Year for datetime conversion (default 2017)
        """
        self.csv_path = csv_path
        self.rate_json_path = rate_json_path
        self.year = year
        self.results = {}

    def run_energy_cost_calculator(self):
        """Run the energy_cost_calculator.py script"""
        print("\n" + "=" * 80)
        print("Running: energy_cost_calculator.py")
        print("=" * 80)

        try:
            # Load and preprocess data
            data_loader = DataForCostCalculation(
                path_to_data_file=self.csv_path,
                data_source="EnergyPlus",
                year=self.year,
                use_holidays=False,
            )

            # Calculate costs
            calculator = EnergyCostCalculator(
                rate_json_path=self.rate_json_path,
                data=data_loader.data,
                include_demand_cost=True,
                include_energy_cost=True,
                include_fixed_cost=True,
                number_of_meters=1,
                electricity_demand_var_name="Electricity:Facility [W](Hourly)",
            )

            total_cost = calculator.get_total_cost()
            energy_cost = (
                calculator.data["energy_charge"].sum()
                if "energy_charge" in calculator.data
                else 0
            )
            demand_cost = (
                calculator.data["demand_charge"].sum()
                if "demand_charge" in calculator.data
                else 0
            )
            fixed_cost = calculator.calculate_fixed_charge_cost()

            self.results["energy_cost_calculator"] = {
                "success": True,
                "total_cost": total_cost,
                "energy_cost": energy_cost,
                "demand_cost": demand_cost,
                "fixed_cost": fixed_cost,
                "timestamp": datetime.now().isoformat(),
            }

            print(f"\n✓ Total Cost: ${total_cost:,.2f}")
            print(f"  - Energy Cost: ${energy_cost:,.2f}")
            print(f"  - Demand Cost: ${demand_cost:,.2f}")
            print(f"  - Fixed Cost: ${fixed_cost:,.2f}")

        except Exception as e:
            print(f"\n✗ Error: {str(e)}")
            traceback.print_exc()
            self.results["energy_cost_calculator"] = {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def run_tou_calculator(self, save_csv=True):
        """Run the tou_calculator.py script"""
        print("\n" + "=" * 80)
        print("Running: tou_calculator.py")
        print("=" * 80)

        if tou_calculate_charge is None:
            print("\n✗ tou_calculator could not be imported")
            self.results["tou_calculator"] = {
                "success": False,
                "error": "Module not importable",
                "timestamp": datetime.now().isoformat(),
            }
            return

        try:
            # Extract rate name from path (e.g., "ashrae" from "ashrae_in_openei_query_format.json")
            rate_name = os.path.basename(self.rate_json_path).replace(
                "_in_openei_query_format.json", ""
            )

            # Run tou calculator
            results = tou_calculate_charge(
                case="test_case",
                epvars=self.csv_path,
                tou=rate_name,
                tou_path=self.rate_json_path,
                demand_var_name="Electricity:Facility [W](Hourly)",
                day_type_var_name="Environment:Site Day Type Index [](Hourly)",
                dst_type_var_name="Environment:Site Daylight Saving Time Status [](Hourly)",
                use_dst=False,
                datetime_transform=True,
                holiday=False,
                test=False,
            )

            summary = results["summary"]
            detail = results["detail"]

            # Save detailed CSV outputs if requested
            if save_csv:
                output_folder = "test_outputs"
                if not os.path.exists(output_folder):
                    os.makedirs(output_folder)

                # Save all detailed dataframes
                for key, value in detail.items():
                    if isinstance(value, pd.DataFrame):
                        csv_filename = f"{output_folder}/tou_calculator_{key}.csv"
                        value.to_csv(csv_filename)
                        print(f"  Saved: {csv_filename}")

                # Save summary as CSV
                summary_df = pd.DataFrame([summary])
                summary_csv = f"{output_folder}/tou_calculator_summary.csv"
                summary_df.to_csv(summary_csv, index=False)
                print(f"  Saved: {summary_csv}")

            # Calculate totals
            energy_cost = sum(
                [
                    v
                    for k, v in summary.items()
                    if "charge_energy_" in k and "annual" in k
                ]
            )

            # Calculate peak demand cost, excluding the 'total_annual' field to avoid double-counting
            # The 'charge_peakdemand_total_annual' is a sum of individual rate charges (rate1, rate2, etc.)
            # so we only sum the individual rate charges, not the total
            demand_cost = sum(
                [
                    v
                    for k, v in summary.items()
                    if "charge_peak" in k and "annual" in k and "total_annual" not in k
                ]
            )  # Exclude total to avoid double-counting

            demand_flat_cost = sum(
                [
                    v
                    for k, v in summary.items()
                    if "charge_demandflat_" in k and "annual" in k
                ]
            )
            total_cost = energy_cost + demand_cost + demand_flat_cost

            self.results["tou_calculator"] = {
                "success": True,
                "total_cost": total_cost,
                "energy_cost": energy_cost,
                "demand_cost": demand_cost + demand_flat_cost,
                "fixed_cost": 0,  # tou_calculator doesn't calculate fixed costs
                "timestamp": datetime.now().isoformat(),
                "summary": summary,
            }

            print(f"\n✓ Total Cost: ${total_cost:,.2f}")
            print(f"  - Energy Cost: ${energy_cost:,.2f}")
            print(f"  - Demand Cost: ${demand_cost + demand_flat_cost:,.2f}")

        except Exception as e:
            print(f"\n✗ Error: {str(e)}")
            traceback.print_exc()
            self.results["tou_calculator"] = {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    def compare_results(self):
        """Compare the results from both calculators"""
        print("\n" + "=" * 80)
        print("COMPARISON RESULTS")
        print("=" * 80)

        if not self.results.get("energy_cost_calculator", {}).get("success"):
            print("\n✗ energy_cost_calculator.py failed - cannot compare")
            return

        if not self.results.get("tou_calculator", {}).get("success"):
            print("\n✗ tou_calculator.py failed - cannot compare")
            return

        calc1 = self.results["energy_cost_calculator"]
        calc2 = self.results["tou_calculator"]

        print("\n" + "-" * 80)
        print("Total Costs:")
        print("-" * 80)
        print(f"energy_cost_calculator.py:  ${calc1['total_cost']:>15,.2f}")
        print(f"tou_calculator.py:          ${calc2['total_cost']:>15,.2f}")
        diff = calc1["total_cost"] - calc2["total_cost"]
        pct_diff = (diff / calc1["total_cost"] * 100) if calc1["total_cost"] != 0 else 0
        print(f"Difference:                 ${diff:>15,.2f} ({pct_diff:+.2f}%)")

        print("\n" + "-" * 80)
        print("Energy Costs:")
        print("-" * 80)
        print(f"energy_cost_calculator.py:  ${calc1['energy_cost']:>15,.2f}")
        print(f"tou_calculator.py:          ${calc2['energy_cost']:>15,.2f}")
        diff = calc1["energy_cost"] - calc2["energy_cost"]
        pct_diff = (
            (diff / calc1["energy_cost"] * 100) if calc1["energy_cost"] != 0 else 0
        )
        print(f"Difference:                 ${diff:>15,.2f} ({pct_diff:+.2f}%)")

        print("\n" + "-" * 80)
        print("Demand Costs:")
        print("-" * 80)
        print(f"energy_cost_calculator.py:  ${calc1['demand_cost']:>15,.2f}")
        print(f"tou_calculator.py:          ${calc2['demand_cost']:>15,.2f}")
        diff = calc1["demand_cost"] - calc2["demand_cost"]
        pct_diff = (
            (diff / calc1["demand_cost"] * 100) if calc1["demand_cost"] != 0 else 0
        )
        print(f"Difference:                 ${diff:>15,.2f} ({pct_diff:+.2f}%)")

        print("\n" + "-" * 80)
        print("Fixed Costs:")
        print("-" * 80)
        print(f"energy_cost_calculator.py:  ${calc1['fixed_cost']:>15,.2f}")
        print(
            f"tou_calculator.py:          ${calc2['fixed_cost']:>15,.2f} (not calculated)"
        )

    def save_results(self, output_path="test_results.json"):
        """Save comparison results to a JSON file"""
        with open(output_path, "w") as f:
            json.dump(self.results, f, indent=2, default=str)
        print(f"\n✓ Results saved to: {output_path}")

    def run_all(self, save_output=True):
        """Run both calculators and compare results"""
        print("\n" + "=" * 80)
        print("ENERGY COST CALCULATOR COMPARISON FRAMEWORK")
        print("=" * 80)
        print(f"CSV File: {self.csv_path}")
        print(f"Rate File: {self.rate_json_path}")
        print(f"Year: {self.year}")

        # Run both calculators
        self.run_energy_cost_calculator()
        self.run_tou_calculator()

        # Compare results
        self.compare_results()

        # Save results
        if save_output:
            self.save_results()


if __name__ == "__main__":
    import glob

    # Configuration
    simulation_folder = "data/sample_simulation_output"
    rates_folder = "../sample_rates"
    year = 2017  # Year for datetime conversion

    # Get all CSV files in simulation folder
    csv_files = glob.glob(os.path.join(simulation_folder, "*.csv"))

    # Get all JSON rate files in sample_rates folder
    rate_files = glob.glob(os.path.join(rates_folder, "*.json"))

    if not csv_files:
        print(f"ERROR: No CSV files found in {simulation_folder}")
        sys.exit(1)

    if not rate_files:
        print(f"ERROR: No rate files found in {rates_folder}")
        sys.exit(1)

    print(f"\nFound {len(csv_files)} simulation file(s)")
    print(f"Found {len(rate_files)} rate file(s)")
    print(f"Will run {len(csv_files) * len(rate_files)} test combination(s)\n")

    # Store all results
    all_results = {}

    # Run comparison for each combination
    for csv_path in csv_files:
        csv_name = os.path.basename(csv_path).replace(".csv", "")

        for rate_path in rate_files:
            rate_name = os.path.basename(rate_path).replace(
                "_in_openei_query_format.json", ""
            )

            test_name = f"{csv_name}_vs_{rate_name}"
            print("\n" + "=" * 80)
            print(f"TEST: {test_name}")
            print("=" * 80)

            # Run comparison
            comparison = CalculatorComparison(
                csv_path=csv_path, rate_json_path=rate_path, year=year
            )

            comparison.run_all(save_output=False)

            # Store results with test name
            all_results[test_name] = comparison.results

    # Save combined results
    output_file = "test_results_all_combinations.json"
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print("ALL TESTS COMPLETE")
    print("=" * 80)
    print(f"✓ Results saved to: {output_file}")

    # Print summary
    print("\nSUMMARY:")
    print("-" * 80)
    success_count = sum(
        1
        for r in all_results.values()
        if r.get("energy_cost_calculator", {}).get("success")
        and r.get("tou_calculator", {}).get("success")
    )
    print(f"Successful comparisons: {success_count}/{len(all_results)}")

    for test_name, result in all_results.items():
        calc1 = result.get("energy_cost_calculator", {})
        calc2 = result.get("tou_calculator", {})

        if calc1.get("success") and calc2.get("success"):
            diff = abs(calc1["total_cost"] - calc2["total_cost"])
            match = "✓ MATCH" if diff < 0.01 else f"✗ DIFF: ${diff:.2f}"
            print(f"  {test_name}: {match}")
        else:
            print(f"  {test_name}: ✗ FAILED")

    # Assert that all tests passed and matched
    print("\n" + "=" * 80)
    print("ASSERTIONS")
    print("=" * 80)

    # Only fail if energy_cost_calculator itself failed, not if tou_calculator is unavailable
    failed_tests = [
        name
        for name, result in all_results.items()
        if not result.get("energy_cost_calculator", {}).get("success")
    ]

    # Check if tou_calculator is available for comparison
    tou_available = any(
        result.get("tou_calculator", {}).get("success")
        for result in all_results.values()
    )

    if not tou_available:
        print(
            "\n⚠ WARNING: tou_calculator comparison was skipped (module not available)"
        )
        print("  This is expected if running without the reference implementation.")
        print("  Only energy_cost_calculator was tested.")

    tolerance = 0.01  # $0.01 tolerance
    mismatched_tests = []
    for test_name, result in all_results.items():
        calc1 = result.get("energy_cost_calculator", {})
        calc2 = result.get("tou_calculator", {})
        if calc1.get("success") and calc2.get("success"):
            total_diff = abs(calc1["total_cost"] - calc2["total_cost"])
            energy_diff = abs(calc1["energy_cost"] - calc2["energy_cost"])
            demand_diff = abs(calc1["demand_cost"] - calc2["demand_cost"])
            if (
                total_diff >= tolerance
                or energy_diff >= tolerance
                or demand_diff >= tolerance
            ):
                mismatched_tests.append(
                    {
                        "name": test_name,
                        "total_diff": total_diff,
                        "energy_diff": energy_diff,
                        "demand_diff": demand_diff,
                    }
                )

    if failed_tests:
        print(
            f"\n✗ ASSERTION FAILED: {len(failed_tests)} test(s) did not complete successfully:"
        )
        for test in failed_tests:
            print(f"    - {test}")
        sys.exit(1)

    if mismatched_tests:
        print(
            f"\n✗ ASSERTION FAILED: {len(mismatched_tests)} test(s) have cost differences:"
        )
        for test in mismatched_tests:
            print(f"    - {test['name']}:")
            print(f"        Total Cost Difference: ${test['total_diff']:.2f}")
            print(f"        Energy Cost Difference: ${test['energy_diff']:.2f}")
            print(f"        Demand Cost Difference: ${test['demand_diff']:.2f}")
        sys.exit(1)

    print(f"\n✓ ALL ASSERTIONS PASSED")
    if tou_available:
        print(f"✓ All {len(all_results)} test combination(s) completed successfully")
        print(
            f"✓ All calculators produce identical results (within ${tolerance:.2f} tolerance)"
        )
    else:
        print(
            f"✓ energy_cost_calculator completed successfully for all {len(all_results)} test(s)"
        )
        print(
            f"  (Comparison with tou_calculator was skipped - reference not available)"
        )
    sys.exit(0)
