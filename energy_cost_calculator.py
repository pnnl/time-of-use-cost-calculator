import logging, sys, os
import pandas as pd
import numpy as np
import json
import argparse
from helpers.data_loader import DataForCostCalculation
from helpers.openei_helpers import get_by_label, get_processed_data

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


class EnergyCostCalculator:
    """Calculate energy costs based on utility rate structures and usage data.

    This class implements energy cost calculations for various utility rate structures
    including time-of-use rates, tiered rates, demand charges, and fixed charges.
    Supports loading rate data from either OpenEI API or local JSON files.

    Attributes:
        rate_label (str): OpenEI rate label for API lookup.
        rate_json_path (str): Path to local JSON file containing rate data.
        data (pd.DataFrame): Timestamped energy usage data.
        include_demand_cost (bool): Whether to calculate demand charges.
        include_energy_cost (bool): Whether to calculate energy charges.
        include_fixed_cost (bool): Whether to calculate fixed charges.
        number_of_meters (int): Number of meters for fixed charge calculation.
        electricity_demand_var_name (str): Column name for electricity demand data.
        electricity_energy_var_name (str): Column name for electricity energy data (e.g., "Electricity:Facility [kWh](Hourly)"). When provided, energy cost calculation uses this column directly instead of converting from demand.
        add_adjustment_to_rate (bool): Whether to apply rate adjustments.
        rate (dict): Loaded rate structure data.

    Example:
        >>> calculator = EnergyCostCalculator(
        ...     rate_json_path="rate.json",
        ...     data=usage_data,
        ...     include_energy_cost=True,
        ...     include_demand_cost=True,
        ...     electricity_demand_var_name="Electricity:Facility [W](Hourly)"
        ... )
        >>> total_cost = calculator.get_total_cost()
    """

    def __init__(
        self,
        rate_label=None,
        rate_json_path=None,
        data=None,
        include_demand_cost=False,
        include_energy_cost=False,
        include_fixed_cost=False,
        number_of_meters=1,
        electricity_demand_var_name=None,
        electricity_energy_var_name=None,
        add_adjustment_to_rate=True,
        api_key=None,
    ):
        self.rate_label = rate_label
        self.rate_json_path = rate_json_path
        self.api_key = api_key
        self.data = data
        self.include_demand_cost = include_demand_cost
        self.include_energy_cost = include_energy_cost
        self.include_fixed_cost = include_fixed_cost
        if number_of_meters < 1:
            logging.warning(
                f"Number of meters cannot be less than 1. Setting number_of_meters to 1."
            )
            number_of_meters = 1
        self.number_of_meters = number_of_meters

        # Load rate from either JSON file or API label
        self.rate = self._load_rate()

        self.electricity_demand_var_name = electricity_demand_var_name
        self.electricity_energy_var_name = electricity_energy_var_name
        self.add_adjustment_to_rate = add_adjustment_to_rate
        self._energy_cost_calculated = False
        self._demand_cost_calculated = False

    def _load_rate(self):
        """Load rate data from either a JSON file or API using rate label.

        Returns:
            dict: Rate data structure
        """
        # Priority: JSON file path takes precedence over rate label
        if self.rate_json_path is not None:
            if not os.path.exists(self.rate_json_path):
                logging.error(f"Rate JSON file not found: {self.rate_json_path}")
                return None

            try:
                with open(self.rate_json_path, "r") as f:
                    rate_data = json.load(f)
                logging.info(f"Loaded rate from JSON file: {self.rate_json_path}")
                return rate_data
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing JSON file {self.rate_json_path}: {e}")
                return None
            except Exception as e:
                logging.error(f"Error reading JSON file {self.rate_json_path}: {e}")
                return None

        elif self.rate_label is not None:
            if self.api_key is None:
                logging.error(
                    "API key must be provided when using rate_label to fetch from OpenEI API."
                )
                return None
            try:
                rate_data = get_by_label(label=self.rate_label, apikey=self.api_key)
                logging.info(f"Loaded rate from API using label: {self.rate_label}")
                return rate_data
            except Exception as e:
                logging.error(
                    f"Error fetching rate from API with label {self.rate_label}: {e}"
                )
                return None

        else:
            logging.error("Either rate_label or rate_json_path must be provided.")
            return None

    def _get_expected_demand_unit(self):
        """Get the expected demand unit from the rate structure.

        Returns:
            str: Expected demand unit (e.g., 'kW'), or None if not specified in rate.
        """
        # Check for various demand unit fields in the rate structure
        if "demandunits" in self.rate:
            return self.rate["demandunits"]
        elif "demandrateunit" in self.rate:
            return self.rate["demandrateunit"]
        elif "flatdemandunit" in self.rate:
            return self.rate["flatdemandunit"]
        return None

    def _get_expected_energy_unit(self):
        """Get the expected energy unit from the rate structure.

        Returns:
            str: Expected energy unit (e.g., 'kWh'), or None if not specified in rate.
        """
        # Check for energy unit fields in the rate structure
        if "energyunits" in self.rate:
            return self.rate["energyunits"]
        # Default to kWh as it's the standard for energy rates
        return "kWh"

    def _extract_unit_from_column_name(self, column_name):
        """Extract unit from column name (e.g., '[W]' from 'Electricity:Facility [W](Hourly)').

        Args:
            column_name (str): Column name containing unit in brackets.

        Returns:
            str: Extracted unit, or None if not found.
        """
        if "[" in column_name and "]" in column_name:
            return column_name.split("[")[-1].split("]")[0].strip()
        return None

    def _convert_power_to_kw(self, value, from_unit):
        """Convert power value to kW.

        Args:
            value (float): Power value to convert.
            from_unit (str): Source unit ('W', 'kW', 'MW').

        Returns:
            float: Value converted to kW.
        """
        from_unit_lower = from_unit.lower()
        if from_unit_lower == "w":
            return value / 1000
        elif from_unit_lower == "kw":
            return value
        elif from_unit_lower == "mw":
            return value * 1000
        else:
            logging.warning(
                f"Unknown power unit '{from_unit}'. Assuming it's already in kW."
            )
            return value

    def _convert_energy_to_kwh(self, value, from_unit):
        """Convert energy value to kWh.

        Args:
            value (float): Energy value to convert.
            from_unit (str): Source unit ('J', 'Wh', 'kWh', 'MWh').

        Returns:
            float: Value converted to kWh.
        """
        from_unit_lower = from_unit.lower()
        if from_unit_lower == "j":
            return value / 3_600_000
        elif from_unit_lower == "wh":
            return value / 1000
        elif from_unit_lower == "kwh":
            return value
        elif from_unit_lower == "mwh":
            return value * 1000
        else:
            logging.warning(
                f"Unknown energy unit '{from_unit}'. Assuming it's already in kWh."
            )
            return value

    def _validate_demand_units(self, data_unit):
        """Validate that demand units are compatible between data and rate.

        Args:
            data_unit (str): Unit extracted from data column.

        Returns:
            bool: True if units are valid and compatible.
        """
        expected_unit = self._get_expected_demand_unit()

        if expected_unit:
            logging.info(f"Rate expects demand in: {expected_unit}")
            logging.info(f"Data provides demand in: {data_unit}")

            # Verify conversion produces the expected unit
            if expected_unit.lower() != "kw":
                logging.warning(
                    f"Rate expects demand in '{expected_unit}' but calculator converts to 'kW'. Results may be incorrect."
                )
                return False
        else:
            logging.info(
                f"Rate does not specify demand units. Data unit: {data_unit}, converting to kW"
            )

        return True

    def _validate_energy_units(self, data_unit):
        """Validate that energy units are compatible between data and rate.

        Args:
            data_unit (str): Unit extracted from data column (power unit like 'W').

        Returns:
            bool: True if units are valid and compatible.
        """
        expected_unit = self._get_expected_energy_unit()

        if expected_unit:
            logging.info(f"Rate expects energy in: {expected_unit}")
            if data_unit.lower() != "kwh":
                logging.info(
                    f"Data provides power in: {data_unit}, will be converted to kWh"
                )
            else:
                logging.info(f"Data provides energy in: {data_unit}")

            # Verify conversion produces the expected unit
            if expected_unit.lower() != "kwh":
                logging.warning(
                    f"Rate expects energy in '{expected_unit}' but calculator converts to 'kWh'. Results may be incorrect."
                )
                return False
        else:
            logging.info(
                f"Rate does not specify energy units. Data unit: {data_unit}, converting to kWh"
            )

        return True

    def get_total_cost(self, add_adjustment_to_rate=True):
        # Validate inputs
        if self.rate is None:
            logging.error("No valid rate data available. Cannot calculate cost.")
            return 0
        if self.data is None:
            logging.error("No data provided for cost calculation.")
            return 0

        # Energy cost calculation
        energy_cost = (
            self.calculate_energy_cost(add_adjustment_to_rate)
            if self.include_energy_cost
            else 0
        )

        # Fixed charges calculation
        fixed_cost = (
            self.calculate_fixed_charge_cost() if self.include_fixed_cost else 0
        )

        # Demand cost calculation
        demand_cost = (
            self.calculate_demand_cost(add_adjustment_to_rate)
            if self.include_demand_cost
            else 0
        )

        # Total cost calculation
        total_cost = energy_cost + fixed_cost + demand_cost

        return total_cost

    def calculate_demand_cost(self, add_adjustment_to_rate=True):
        """Calculate demand charges based on peak usage and rate structure.

        Computes demand charges using either flat demand structure or time-of-use
        demand structure. Handles tiered rates and applies rate adjustments if specified.

        Args:
            add_adjustment_to_rate (bool): Whether to apply rate adjustments. Defaults to True.

        Returns:
            float: Total demand charges in dollars, or 0 if calculation fails.

        Note:
            Results are also stored in self.data['demand_charge'] column.
            Supports flat demand and time-of-use demand structures.
            Coincident demand structures are not currently supported.
        """
        if self._demand_cost_calculated:
            return self.data["demand_charge"].sum()

        if self.electricity_demand_var_name is None:
            logging.error(
                "Electricity demand variable name must be provided for demand cost calculation."
            )
            return 0

        # Get variable names
        day_type_var_cols = [
            col for col in self.data.columns if "site day type index" in col.lower()
        ]
        if not day_type_var_cols:
            logging.error("No 'site day type index' column found in data.")
            return 0
        day_type_var_name = day_type_var_cols[0]

        demand_var_cols = [
            col
            for col in self.data.columns
            if col.lower() == self.electricity_demand_var_name.lower()
        ]
        if not demand_var_cols:
            logging.error(
                f"Electricity demand variable '{self.electricity_demand_var_name}' not found in data columns."
            )
            return 0
        demand_var_name = demand_var_cols[0]

        # Extract demand unit from variable name
        demand_unit = self._extract_unit_from_column_name(demand_var_name)
        if demand_unit is None:
            logging.warning(
                f"Could not extract demand unit from variable name '{demand_var_name}'. Assuming demand is in watts (W)."
            )
            demand_unit = "W"

        # Validate units match between data and rate
        self._validate_demand_units(demand_unit)

        # Convert rate to pandas dataframes
        rate = get_processed_data(self.rate)
        if "demand" in rate:
            rate_demand = rate["demand"]
        else:
            logging.error(
                f"Demand rate data not found in rate '{self.rate_label}'. Demand cost calculation will be set to 0."
            )
            return 0

        # Initialize demand charge columns in the data
        self.data["demand_charge"] = 0.0
        self.data["demand_charge_flat"] = 0.0  # Track flat demand charges separately
        self.data["demand_charge_tou"] = 0.0  # Track TOU demand charges separately
        self.data["demand_usage_kW"] = 0.0
        self.data["demand_charge_rate"] = 0.0
        self.data["demand_peak_period"] = 0

        # Convert demand usage to kW and store in a new column
        for idx, row in self.data.iterrows():
            usage = row[demand_var_name]
            # Convert usage to kW using helper method
            usage = self._convert_power_to_kw(usage, demand_unit)
            self.data.at[idx, "demand_usage_kW"] = usage

        # Case 1: flat demand structure
        if "flatdemandstructure" in rate_demand:
            # Get maximum monthly demand index
            monthly_max_demand_indexes = self.data.groupby(self.data.index.month)[
                "demand_usage_kW"
            ].idxmax()

            # Get flat demand charge for each month
            for (
                month_num,
                monthly_max_demand_index,
            ) in monthly_max_demand_indexes.items():
                rate_demand_period = rate_demand["flatdemandmonths"].loc[month_num][
                    "flat"
                ]
                rate_demand_structure_df = rate_demand["flatdemandstructure"]

                # Get the rate for the current period and maximum monthly kW based on the tiered structure
                selected_tier = 0
                tier_found = False
                for _, tier_row in rate_demand_structure_df.iterrows():
                    max_kW = (
                        tier_row.get("max", float("inf"))
                        if "max" in tier_row.index
                        else float("inf")
                    )
                    if (
                        self.data.at[monthly_max_demand_index, "demand_usage_kW"]
                        > max_kW
                    ):
                        continue
                    else:
                        selected_tier = tier_row["tier"]
                        tier_found = True
                        break

                if not tier_found:
                    # Use the last (highest) tier if usage exceeds all tier maxes
                    selected_tier = rate_demand_structure_df.iloc[-1]["tier"]
                    logging.warning(
                        f"Demand usage exceeds all tier maximums for month {monthly_max_demand_index.month}. Using highest tier."
                    )

                period_tier_rate = rate_demand_structure_df.loc[
                    (rate_demand_structure_df["period"] == rate_demand_period)
                    & (rate_demand_structure_df["tier"] == selected_tier)
                ]
                charge_rate = (
                    period_tier_rate["rate"].values[0]
                    if len(period_tier_rate) > 0
                    else 0
                )
                if (
                    "adj" in period_tier_rate.columns
                    and len(period_tier_rate) > 0
                    and add_adjustment_to_rate
                ):
                    adjustment = period_tier_rate["adj"].values[0]
                    # Other tools like SAM for example appears to add the adjustment to the rate, see:
                    # https://github.com/NatLabRockies/SAM/blob/984b44c43379b04e0e468d99ea3536a709f1fd05/src/urdb.cpp#L979
                    charge_rate += adjustment

                self.data.at[monthly_max_demand_index, "demand_charge_rate"] = (
                    charge_rate
                )
                # Store flat demand charge separately and add to total
                flat_charge = (
                    charge_rate
                    * self.data.at[monthly_max_demand_index, "demand_usage_kW"]
                )
                self.data.at[monthly_max_demand_index, "demand_charge_flat"] = (
                    flat_charge
                )
                self.data.at[monthly_max_demand_index, "demand_charge"] += flat_charge

        # Case 2: time-of-use demand structure (additive to flat demand)
        if "demandratestructure" in rate_demand:
            # First pass: assign rate period to each timestep
            for idx, row in self.data.iterrows():
                # Get the rate period
                day_type = row[day_type_var_name]
                if (day_type >= 2) and (day_type <= 6):
                    rate_demand_schedule = rate_demand[f"demandweekdayschedule"]
                else:  # all other days are using weekend schedule
                    rate_demand_schedule = rate_demand[f"demandweekendschedule"]

                rate_demand_structure_df = rate_demand[f"demandratestructure"]
                if "period" not in rate_demand_structure_df.columns:
                    raise ValueError(
                        f"Demand rate structure for rate '{self.rate_label}' is missing a 'period' column."
                    )
                try:
                    rate_demand_period = rate_demand_schedule.loc[idx.month, idx.hour]
                except KeyError:
                    logging.warning(
                        f"No rate schedule found for month {idx.month}, hour {idx.hour}. Skipping this timestep."
                    )
                    continue

                rate_demand_structure_df = rate_demand_structure_df[
                    rate_demand_structure_df["period"] == rate_demand_period
                ]

                # Get the rate for the current period
                selected_tier = 0
                tier_found = False
                for _, tier_row in rate_demand_structure_df.iterrows():
                    max_kW = (
                        tier_row.get("max", float("inf"))
                        if "max" in tier_row.index
                        else float("inf")
                    )
                    if row["demand_usage_kW"] > max_kW:
                        continue
                    else:
                        selected_tier = tier_row["tier"]
                        tier_found = True
                        break

                if not tier_found:
                    # Use the last (highest) tier if usage exceeds all tier maxes
                    selected_tier = rate_demand_structure_df.iloc[-1]["tier"]

                period_tier_rate = rate_demand_structure_df.loc[
                    (rate_demand_structure_df["period"] == rate_demand_period)
                    & (rate_demand_structure_df["tier"] == selected_tier)
                ]
                charge_rate = (
                    period_tier_rate["rate"].values[0]
                    if len(period_tier_rate) > 0
                    else 0
                )
                if (
                    "adj" in period_tier_rate.columns
                    and len(period_tier_rate) > 0
                    and add_adjustment_to_rate
                ):
                    adjustment = period_tier_rate["adj"].values[0]
                    charge_rate += adjustment

                self.data.at[idx, "demand_charge_rate"] = charge_rate
                self.data.at[idx, "demand_peak_period"] = rate_demand_period

            # Second pass: find monthly peak for each TOU period
            for month_num, month_data in self.data.groupby(self.data.index.month):
                for period in month_data["demand_peak_period"].unique():
                    period_data = month_data[month_data["demand_peak_period"] == period]
                    if len(period_data) > 0:
                        # Find the index with maximum demand in this period for the entire month
                        max_demand_idx = period_data["demand_usage_kW"].idxmax()
                        max_demand_kW = period_data.loc[
                            max_demand_idx, "demand_usage_kW"
                        ]
                        charge_rate = period_data.loc[
                            max_demand_idx, "demand_charge_rate"
                        ]

                        # Calculate TOU demand charge and ADD to existing charges
                        # Only apply charge if the rate is non-zero (skip period 0 with $0/kW rate)
                        if charge_rate > 0:
                            tou_charge = max_demand_kW * charge_rate
                            self.data.at[
                                max_demand_idx, "demand_charge_tou"
                            ] += tou_charge
                            self.data.at[max_demand_idx, "demand_charge"] += tou_charge

        # Case 3: coincident demand structure - currently not supported in demand cost calculation
        if "coincidentdemandstructure" in rate_demand:
            coincident_structure = rate_demand["coincidentdemandstructure"]
            logging.warning(
                f"Rate contains 'coincidentdemandstructure' with structure: {coincident_structure}. "
                "Coincident demand charges are NOT currently supported in the cost calculation. "
                "This part of the demand cost will be set to $0. "
                "The calculated demand costs may be lower than actual billed amounts."
            )

        self._demand_cost_calculated = True
        return self.data["demand_charge"].sum()

    def calculate_fixed_charge_cost(self):
        """Calculate fixed charges based on rate structure and number of meters.

        Computes fixed charges that may vary by time period (daily, monthly, yearly)
        and accounts for multiple meters if applicable.

        Returns:
            float: Total fixed charges in dollars.

        Note:
            Supports fixed charges in $/day, $/month, and $/year units.
            Accounts for both fixedchargefirstmeter and fixedchargeeaaddl rates.
        """
        fixed_charge_cost = 0
        if "fixedchargeunits" in self.rate:
            units = self.rate["fixedchargeunits"]
            if units == "$/day":
                days = len(pd.unique(self.data.index.date))
                fixed_charge_cost = days * (
                    self.rate.get("fixedchargefirstmeter", 0)
                    + self.rate.get("fixedchargeeaaddl", 0)
                    * (self.number_of_meters - 1)
                )
            elif units == "$/month":
                months = len(pd.unique(self.data.index.month))
                fixed_charge_cost = months * (
                    self.rate.get("fixedchargefirstmeter", 0)
                    + self.rate.get("fixedchargeeaaddl", 0)
                    * (self.number_of_meters - 1)
                )
            elif units == "$/year":
                years = len(pd.unique(self.data.index.year))
                fixed_charge_cost = years * (
                    self.rate.get("fixedchargefirstmeter", 0)
                    + self.rate.get("fixedchargeeaaddl", 0)
                    * (self.number_of_meters - 1)
                )
            else:
                logging.warning(
                    f"Unrecognized fixed charge units '{units}' for rate '{self.rate_label}'. Fixed charge cost will be set to 0."
                )
        if "fixedmonthlycharge" in self.rate:
            months = len(pd.unique(self.data.index.month))
            fixed_charge_cost += months * self.rate["fixedmonthlycharge"]
        return fixed_charge_cost

    def calculate_energy_cost(self, add_adjustment_to_rate=True):
        """Calculate energy charges based on consumption and rate structure.

        Computes energy charges using time-of-use rates and tiered pricing structures.
        When electricity_energy_var_name is set, uses actual energy data directly.
        Otherwise, converts demand data (W, kW, MW) to kWh using timestep duration.

        Args:
            add_adjustment_to_rate (bool): Whether to apply rate adjustments. Defaults to True.

        Returns:
            float: Total energy charges in dollars, or 0 if calculation fails.

        Note:
            Results are stored in self.data columns: 'energy_charge', 'energy_usage_kWh',
            'energy_charge_rate', and 'fraction_of_hour'.
            Supports cumulative tiered pricing based on total kWh consumption.
        """
        if self._energy_cost_calculated:
            return self.data["energy_charge"].sum()

        use_energy_var = self.electricity_energy_var_name is not None

        if not use_energy_var and self.electricity_demand_var_name is None:
            logging.error(
                "Either electricity_energy_var_name or electricity_demand_var_name must be provided for energy cost calculation."
            )
            return 0

        # Get variable names
        day_type_var_cols = [
            col for col in self.data.columns if "site day type index" in col.lower()
        ]
        if not day_type_var_cols:
            logging.error("No 'site day type index' column found in data.")
            return 0
        day_type_var_name = day_type_var_cols[0]

        if use_energy_var:
            energy_var_cols = [
                col
                for col in self.data.columns
                if col.lower() == self.electricity_energy_var_name.lower()
            ]
            if not energy_var_cols:
                logging.error(
                    f"Electricity energy variable '{self.electricity_energy_var_name}' not found in data columns."
                )
                return 0
            energy_var_name = energy_var_cols[0]
            energy_unit = self._extract_unit_from_column_name(energy_var_name)
            if energy_unit is None:
                logging.warning(
                    f"Could not extract energy unit from variable name '{energy_var_name}'. Assuming kWh."
                )
                energy_unit = "kWh"
            self._validate_energy_units(energy_unit)
        else:
            demand_var_cols = [
                col
                for col in self.data.columns
                if col.lower() == self.electricity_demand_var_name.lower()
            ]
            if not demand_var_cols:
                logging.error(
                    f"Electricity demand variable '{self.electricity_demand_var_name}' not found in data columns."
                )
                return 0
            demand_var_name = demand_var_cols[0]
            demand_unit = self._extract_unit_from_column_name(demand_var_name)
            if demand_unit is None:
                logging.warning(
                    f"Could not extract demand unit from variable name '{demand_var_name}'. Assuming demand is in watts (W)."
                )
                demand_unit = "W"
            self._validate_demand_units(demand_unit)

        # Convert rate to pandas dataframes
        rate = get_processed_data(self.rate)
        if "energy" in rate:
            rate_energy = rate["energy"]
        else:
            logging.error(
                f"Energy rate data not found in rate '{self.rate_label}'. Energy cost calculation will be set to 0."
            )
            return 0

        self.data["energy_charge"] = 0.0
        self.data["energy_usage_kWh"] = 0.0
        self.data["energy_charge_rate"] = 0.0
        self.data["fraction_of_hour"] = 0.0
        cumulative_kWh = 0
        current_month = None
        for idx, row in self.data.iterrows():
            if idx.month != current_month:
                if current_month is not None:
                    logging.info(
                        f"Month {current_month}: cumulative energy usage = {cumulative_kWh:.4f} kWh"
                    )
                cumulative_kWh = 0
                current_month = idx.month
            # Get the rate period
            day_type = row[day_type_var_name]
            if (day_type >= 2) and (day_type <= 6):
                rate_energy_schedule = rate_energy["energyweekdayschedule"]
            else:
                rate_energy_schedule = rate_energy["energyweekendschedule"]
            try:
                rate_energy_period = rate_energy_schedule.loc[idx.month, idx.hour]
            except KeyError:
                logging.warning(
                    f"No rate schedule found for month {idx.month}, hour {idx.hour}. Using tier 0."
                )
                selected_tier = 0
                charge_rate = 0
                # Skip the rest of this iteration
                self.data.at[idx, "energy_charge"] = 0.0
                self.data.at[idx, "energy_usage_kWh"] = 0.0
                self.data.at[idx, "energy_charge_rate"] = 0.0
                self.data.at[idx, "fraction_of_hour"] = 0.0
                continue

            # Get the rate for the current period and cumulative kWh based on the tiered structure
            rate_energy_structure_df = rate_energy["energyratestructure"]
            if "period" not in rate_energy_structure_df.columns:
                raise ValueError(
                    f"Energy rate structure for rate '{self.rate_label}' is missing a 'period' column."
                )
            rate_energy_structure_df = rate_energy_structure_df[
                rate_energy_structure_df["period"] == rate_energy_period
            ]
            selected_tier = 0
            tier_found = False
            for _, tier_row in rate_energy_structure_df.iterrows():
                max_kWh = (
                    tier_row.get("max", float("inf"))
                    if "max" in tier_row
                    else float("inf")
                )
                if tier_row["unit"] != "kWh":
                    logging.warning(
                        f"Tier {tier_row['tier']} uses {tier_row['unit']} for rate '{self.rate_label}'. Only 'kWh' is supported for energy rates. This tier will be skipped in energy cost calculation."
                    )
                    continue
                if cumulative_kWh > max_kWh:
                    continue
                else:
                    selected_tier = tier_row["tier"]
                    tier_found = True
                    break

            if not tier_found and len(rate_energy_structure_df) > 0:
                # Use the last (highest) tier if usage exceeds all tier maxes
                valid_tiers = rate_energy_structure_df[
                    rate_energy_structure_df["unit"] == "kWh"
                ]
                if len(valid_tiers) > 0:
                    selected_tier = valid_tiers.iloc[-1]["tier"]
            if "rate" in rate_energy_structure_df.columns:
                period_tier_rate = rate_energy_structure_df.loc[
                    (rate_energy_structure_df["period"] == rate_energy_period)
                    & (rate_energy_structure_df["tier"] == selected_tier)
                ]
                charge_rate = (
                    period_tier_rate["rate"].values[0]
                    if len(period_tier_rate) > 0
                    else 0
                )
                if (
                    "adj" in period_tier_rate.columns
                    and len(period_tier_rate) > 0
                    and add_adjustment_to_rate
                ):
                    adjustment = period_tier_rate["adj"].values[0]
                    # Other tools like SAM for example appears to add the adjustment to the rate, see:
                    # https://github.com/NatLabRockies/SAM/blob/984b44c43379b04e0e468d99ea3536a709f1fd05/src/urdb.cpp#L881
                    charge_rate += adjustment
            else:
                logging.warning(
                    f"The 'rate' column not found in energy rate structure for rate '{self.rate_label}'. Energy cost for this timestep will be set to 0."
                )
                charge_rate = 0

            if use_energy_var:
                # Use actual energy data directly
                usage = self._convert_energy_to_kwh(row[energy_var_name], energy_unit)
                time_diff_hours = 0.0
            else:
                # Calculate time difference from previous timestamp in hours
                if idx == self.data.index[0]:
                    # For first timestep, assume standard interval from next timestep
                    if len(self.data.index) > 1:
                        time_diff_hours = (
                            self.data.index[1] - self.data.index[0]
                        ).total_seconds() / 3600
                    else:
                        time_diff_hours = 1.0  # Default to 1 hour if only one timestep
                else:
                    prev_idx = self.data.index[self.data.index.get_loc(idx) - 1]
                    time_diff_hours = (idx - prev_idx).total_seconds() / 3600

                # Demand to energy
                usage = time_diff_hours * row[demand_var_name]
                usage = self._convert_power_to_kw(usage, demand_unit)

            cumulative_kWh += usage

            # Calculate charge
            charge = charge_rate * usage

            # Store details for this timestep
            self.data.at[idx, "energy_charge"] = charge
            self.data.at[idx, "energy_usage_kWh"] = usage
            self.data.at[idx, "energy_charge_rate"] = charge_rate
            self.data.at[idx, "fraction_of_hour"] = time_diff_hours

        if current_month is not None:
            logging.info(
                f"Month {current_month}: cumulative energy usage = {cumulative_kWh:.4f} kWh"
            )
        self._energy_cost_calculated = True
        return self.data["energy_charge"].sum()

    def get_summary(self, add_adjustment_to_rate=True):
        """Generate a summary dictionary of all calculated costs.

        Returns:
            dict: Summary containing total costs and breakdowns by month and charge type.
        """
        summary = {}

        # Calculate totals
        total_cost = self.get_total_cost(add_adjustment_to_rate)
        energy_cost = (
            self.data["energy_charge"].sum()
            if "energy_charge" in self.data.columns
            else 0
        )
        demand_cost = (
            self.data["demand_charge"].sum()
            if "demand_charge" in self.data.columns
            else 0
        )
        demand_flat_cost = (
            self.data["demand_charge_flat"].sum()
            if "demand_charge_flat" in self.data.columns
            else 0
        )
        demand_tou_cost = (
            self.data["demand_charge_tou"].sum()
            if "demand_charge_tou" in self.data.columns
            else 0
        )
        fixed_cost = (
            self.calculate_fixed_charge_cost() if self.include_fixed_cost else 0
        )

        # Overall totals
        summary["total_cost"] = total_cost
        summary["energy_cost_total"] = energy_cost
        summary["demand_cost_total"] = demand_cost
        summary["demand_flat_cost_total"] = demand_flat_cost
        summary["demand_tou_cost_total"] = demand_tou_cost
        summary["fixed_cost_total"] = fixed_cost

        # Monthly breakdowns
        if "energy_charge" in self.data.columns:
            monthly_energy = self.data.groupby(self.data.index.month)[
                "energy_charge"
            ].sum()
            for month in range(1, 13):
                summary[f"energy_cost_month_{month:02d}"] = monthly_energy.get(month, 0)

        if "energy_usage_kWh" in self.data.columns:
            monthly_kwh = self.data.groupby(self.data.index.month)[
                "energy_usage_kWh"
            ].sum()
            for month in range(1, 13):
                summary[f"energy_kwh_month_{month:02d}"] = monthly_kwh.get(month, 0)

        if "demand_charge" in self.data.columns:
            monthly_demand_cost = self.data.groupby(self.data.index.month)[
                "demand_charge"
            ].sum()
            for month in range(1, 13):
                summary[f"demand_cost_month_{month:02d}"] = monthly_demand_cost.get(
                    month, 0
                )

        if "demand_usage_kW" in self.data.columns:
            monthly_peak_kw = self.data.groupby(self.data.index.month)[
                "demand_usage_kW"
            ].max()
            for month in range(1, 13):
                summary[f"peak_kw_month_{month:02d}"] = monthly_peak_kw.get(month, 0)

        # Add fixed charges by month
        if self.include_fixed_cost:
            monthly_fixed = (
                fixed_cost / len(pd.unique(self.data.index.month))
                if len(pd.unique(self.data.index.month)) > 0
                else 0
            )
            for month in range(1, 13):
                if month in self.data.index.month.unique():
                    summary[f"fixed_cost_month_{month:02d}"] = monthly_fixed
                else:
                    summary[f"fixed_cost_month_{month:02d}"] = 0

        return summary

    def export_detailed_results(
        self, output_folder="outputs", case_name="case", add_adjustment_to_rate=True
    ):
        """Export detailed calculation results to CSV files.

        Creates multiple CSV files with timestep, daily, and monthly aggregations
        of energy and demand data.

        Args:
            output_folder (str): Folder path where CSV files will be saved. Defaults to 'outputs'.
            case_name (str): Prefix for output file names. Defaults to 'case'.
            add_adjustment_to_rate (bool): Whether to apply rate adjustments. Defaults to True.

        Returns:
            dict: Dictionary with paths to all created files.
        """
        # Create output folder if it doesn't exist
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
            logging.info(f"Created output folder: {output_folder}")

        output_files = {}

        # 1. Save timestep-level data (full DataFrame with all calculated columns)
        timestep_cols = [
            col
            for col in self.data.columns
            if any(
                x in col.lower()
                for x in [
                    "energy_charge",
                    "energy_usage",
                    "energy_charge_rate",
                    "fraction_of_hour",
                    "demand_charge",
                    "demand_usage",
                    "demand_charge_rate",
                    "demand_peak_period",
                ]
            )
        ]

        if timestep_cols:
            timestep_file = os.path.join(
                output_folder, f"{case_name}_timestep_charges.csv"
            )
            self.data[timestep_cols].to_csv(timestep_file)
            output_files["timestep"] = timestep_file
            logging.info(f"Saved timestep data: {timestep_file}")

        # 2. Save energy monthly aggregations
        if "energy_charge" in self.data.columns:
            energy_monthly = self.data.groupby(self.data.index.month).agg(
                {
                    "energy_charge": "sum",
                    "energy_usage_kWh": "sum",
                    "energy_charge_rate": "mean",
                }
            )
            energy_monthly.index.name = "month"
            monthly_file = os.path.join(
                output_folder, f"{case_name}_energy_monthly.csv"
            )
            energy_monthly.to_csv(monthly_file)
            output_files["energy_monthly"] = monthly_file
            logging.info(f"Saved energy monthly data: {monthly_file}")

        # 3. Save energy daily aggregations
        if "energy_charge" in self.data.columns:
            energy_daily = self.data.groupby(
                [self.data.index.month, self.data.index.day]
            ).agg({"energy_charge": "sum", "energy_usage_kWh": "sum"})
            energy_daily.index.names = ["month", "day"]
            daily_file = os.path.join(output_folder, f"{case_name}_energy_daily.csv")
            energy_daily.to_csv(daily_file)
            output_files["energy_daily"] = daily_file
            logging.info(f"Saved energy daily data: {daily_file}")

        # 4. Save demand monthly aggregations
        if "demand_charge" in self.data.columns:
            demand_monthly = self.data.groupby(self.data.index.month).agg(
                {
                    "demand_charge": "sum",
                    "demand_charge_flat": "sum",
                    "demand_charge_tou": "sum",
                    "demand_usage_kW": "max",
                    "demand_charge_rate": "max",
                }
            )
            demand_monthly.index.name = "month"
            demand_monthly_file = os.path.join(
                output_folder, f"{case_name}_demand_monthly.csv"
            )
            demand_monthly.to_csv(demand_monthly_file)
            output_files["demand_monthly"] = demand_monthly_file
            logging.info(f"Saved demand monthly data: {demand_monthly_file}")

        # 5. Save summary
        summary = self.get_summary(add_adjustment_to_rate)
        summary_df = pd.DataFrame([summary])
        summary_file = os.path.join(output_folder, f"{case_name}_summary.csv")
        summary_df.to_csv(summary_file, index=False)
        output_files["summary"] = summary_file
        logging.info(f"Saved summary: {summary_file}")

        # 6. Save full DataFrame with all data
        full_file = os.path.join(output_folder, f"{case_name}_full_data.csv")
        self.data.to_csv(full_file)
        output_files["full_data"] = full_file
        logging.info(f"Saved full data: {full_file}")

        return output_files

    def export_summary_only(
        self, output_path="summary.csv", add_adjustment_to_rate=True
    ):
        """Export only the summary results to a single CSV file.

        Args:
            output_path (str): Path where the summary CSV will be saved. Defaults to 'summary.csv'.
            add_adjustment_to_rate (bool): Whether to apply rate adjustments. Defaults to True.

        Returns:
            str: Path to the created summary file.
        """
        summary = self.get_summary(add_adjustment_to_rate)
        summary_df = pd.DataFrame([summary])
        summary_df.to_csv(output_path, index=False)
        logging.info(f"Saved summary to: {output_path}")
        return output_path


if __name__ == "__main__":
    # Argument parsing and validation
    parser = argparse.ArgumentParser(
        description="Calculate energy costs based on utility rate structures and usage data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python energy_cost_calculator.py --data-file meter_data.csv --data-source energyplus --year 2023 --rate-label "67e97637499bc4a42604d6fb" --number-of-meters 1 --use-holidays --demand-var "Electricity:Facility [W](Hourly)"
  
  python energy_cost_calculator.py -d meter_data.csv -s energyplus -y 2023 -r "67e97637499bc4a42604d6fb" -n 1 --demand-var "Electricity:Facility [W](Hourly)"
        """,
    )

    parser.add_argument(
        "--data-file",
        "-d",
        required=True,
        help="Path to the data file containing energy usage data",
    )

    parser.add_argument(
        "--data-source",
        "-s",
        required=True,
        choices=["energyplus", "csv"],
        help="Source format of the data file",
    )

    parser.add_argument(
        "--datetime-col",
        default=None,
        help="Column name to use as datetime index (required when --data-source csv)",
    )

    parser.add_argument(
        "--year",
        "-y",
        required=True,
        type=int,
        help="Year for the energy data (e.g., 2023)",
    )

    parser.add_argument(
        "--rate-label",
        "-r",
        help='OpenEI rate label identifier (e.g., "67e97637499bc4a42604d6fb")',
    )

    parser.add_argument(
        "--rate-json-path",
        "--tou-path",
        help="Path to local rate JSON file (alternative to --rate-label)",
    )

    parser.add_argument(
        "--api-key",
        "-k",
        help="OpenEI API key for fetching rate data from the API (required when using --rate-label)",
    )

    parser.add_argument(
        "--number-of-meters",
        "-n",
        required=True,
        type=int,
        help="Number of meters for fixed charge calculation (must be >= 1)",
    )

    parser.add_argument(
        "--use-holidays",
        action="store_true",
        help="Include holidays in the calculation",
    )

    parser.add_argument(
        "--demand-var",
        required=False,
        help='Column name for electricity demand data (e.g., "Electricity:Facility [W](Hourly)")',
    )

    parser.add_argument(
        "--skip-rows",
        type=int,
        default=0,
        help="Number of data rows to skip from the beginning of the CSV before processing (default: 0)",
    )

    parser.add_argument(
        "--energy-var",
        required=False,
        help='Column name for electricity energy data (e.g., "Electricity:Facility [kWh](Hourly)"). When provided, energy cost calculation uses this column directly instead of converting from demand.',
    )

    parser.add_argument(
        "--export-detailed",
        action="store_true",
        help="Export detailed results to CSV files (timestep, daily, monthly aggregations)",
    )

    parser.add_argument(
        "--output-folder",
        default="outputs",
        help="Output folder for detailed results (default: outputs)",
    )

    parser.add_argument(
        "--case-name",
        default="case",
        help="Case name prefix for output files (default: case)",
    )

    parser.add_argument(
        "--no-adjustments",
        dest="add_adjustment_to_rate",
        action="store_false",
        default=True,
        help="Disable rate adjustments when calculating costs (default: adjustments enabled)",
    )

    args = parser.parse_args()

    # Validate that at least one of demand-var or energy-var is provided
    if not args.demand_var and not args.energy_var:
        logging.error("Error: Either --demand-var or --energy-var must be provided")
        parser.print_help()
        sys.exit(1)

    # Validate that either rate-label or rate-json-path is provided
    if not args.rate_label and not args.rate_json_path:
        logging.error("Error: Either --rate-label or --rate-json-path must be provided")
        parser.print_help()
        sys.exit(1)

    # Validate that API key is provided when using rate-label
    if args.rate_label and not args.api_key:
        logging.error("Error: --api-key is required when using --rate-label")
        parser.print_help()
        sys.exit(1)

    # Validate file exists
    if not os.path.exists(args.data_file):
        logging.error(f"Error: File '{args.data_file}' does not exist")
        sys.exit(1)

    # Validate rate JSON file exists if provided
    if args.rate_json_path and not os.path.exists(args.rate_json_path):
        logging.error(f"Error: Rate JSON file '{args.rate_json_path}' does not exist")
        sys.exit(1)

    # Validate number of meters
    if args.number_of_meters < 1:
        logging.error("Error: number_of_meters must be at least 1")
        sys.exit(1)

    # Validate csv-specific arguments
    if args.data_source == "csv" and not args.datetime_col:
        logging.error("Error: --datetime-col is required when --data-source is csv")
        sys.exit(1)

    # Load and preprocess data
    data_for_cost_calculation = DataForCostCalculation(
        args.data_file,
        args.data_source,
        args.year,
        args.use_holidays,
        args.skip_rows,
        datetime_col=args.datetime_col,
    )

    # Perform cost calculation
    energy_cost_calculator = EnergyCostCalculator(
        rate_label=args.rate_label,
        rate_json_path=getattr(args, "rate_json_path", None),
        api_key=args.api_key,
        data=data_for_cost_calculation.data,
        include_demand_cost=True,
        include_energy_cost=True,
        include_fixed_cost=True,
        number_of_meters=args.number_of_meters,
        electricity_demand_var_name=args.demand_var,
        electricity_energy_var_name=args.energy_var,
    )
    energy_cost = energy_cost_calculator.get_total_cost(args.add_adjustment_to_rate)

    # Export detailed results if requested
    if args.export_detailed:
        output_files = energy_cost_calculator.export_detailed_results(
            output_folder=args.output_folder,
            case_name=args.case_name,
            add_adjustment_to_rate=args.add_adjustment_to_rate,
        )
        print(f"\nExported detailed results to: {args.output_folder}/")
        for file_type, file_path in output_files.items():
            print(f"  - {file_type}: {file_path}")

    print(f"\nTotal energy cost: ${energy_cost:.2f}")
    print(f"Energy cost breakdown:")
    if energy_cost_calculator.include_energy_cost:
        energy_charges = energy_cost_calculator.data["energy_charge"].sum()
        print(f"  - Energy charges: ${energy_charges:.2f}")
    if energy_cost_calculator.include_demand_cost:
        demand_charges = energy_cost_calculator.data["demand_charge"].sum()
        print(f"  - Demand charges: ${demand_charges:.2f}")
    if energy_cost_calculator.include_fixed_cost:
        # Calculate fixed cost separately since it's not stored in data
        fixed_charges = energy_cost_calculator.calculate_fixed_charge_cost()
        print(f"  - Fixed charges: ${fixed_charges:.2f}")
