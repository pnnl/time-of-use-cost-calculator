import logging
import pandas as pd

from helpers.energyplus_date_helpers import DateTimeEP


class DataForCostCalculation:
    def __init__(
        self,
        path_to_data_file,
        data_source="EnergyPlus",
        year=2000,
        use_holidays=False,
        skip_rows=0,
        use_dst=False,
    ):
        self.path_to_data_file = path_to_data_file
        self.data_source = data_source
        self.use_holidays = use_holidays
        self.skip_rows = skip_rows
        self.use_dst = use_dst
        self.data = self.load_data()
        self.data = self.preprocess_data(year)

    def load_data(self):
        """Load energy simulation data from CSV file.

        Loads data from either a regular CSV file or a gzip-compressed CSV file,
        performs basic validation, and cleans column names.

        Returns:
            pd.DataFrame: Loaded data with cleaned column names, or None if loading fails.

        Raises:
            Logs errors if file cannot be loaded or is empty.
        """
        try:
            # Load the data using pandas, handling both regular and gzipped CSV files
            if self.path_to_data_file.endswith(".gz"):
                data = pd.read_csv(self.path_to_data_file, compression="gzip")
            else:
                data = pd.read_csv(self.path_to_data_file)

            # Check if the data is empty and log a warning if it is
            if data.empty:
                logging.warning(f"The data file {self.path_to_data_file} is empty.")
                return None

            # Remove any leading/trailing whitespace from column names
            data.columns = data.columns.str.strip()

            if self.skip_rows > 0:
                data = data.iloc[self.skip_rows :].reset_index(drop=True)

            return data
        except Exception as e:
            logging.error(f"Error loading data from {self.path_to_data_file}: {e}")
            return None

    def preprocess_data(self, year):
        """Preprocess loaded data according to the data source type.

        Applies data source-specific preprocessing, including datetime conversion,
        daylight saving time handling, and holiday handling for EnergyPlus data.

        Args:
            year (int): Year to use for datetime conversion.

        Returns:
            pd.DataFrame: Preprocessed data with proper datetime index and day types,
                or None if preprocessing fails.
        """
        if self.data is None:
            logging.error("No data to preprocess.")
            return None

        if self.data_source.lower() == "energyplus":
            # Convert EnergyPlus date/time strings to Python datetime objects
            date_helper = DateTimeEP(self.data, year)
            self.data = date_helper.transform()

            # Daylight saving time handling
            dst_type_var_names = [
                col
                for col in self.data.columns
                if "site daylight saving time status" in col.lower()
            ]
            day_type_var_names = [
                col for col in self.data.columns if "site day type index" in col.lower()
            ]
            if self.use_dst:
                if len(dst_type_var_names) == 0 or len(day_type_var_names) == 0:
                    logging.warning(
                        "use_dst=True but 'Site Daylight Saving Time Status' or "
                        "'Site Day Type Index' column not found in data; skipping DST adjustment."
                    )
                else:
                    self.data = date_helper.add_dst_clocktime(
                        day_type_col=day_type_var_names[0],
                        dst_type_col=dst_type_var_names[0],
                    )
                    self.data["original_index"] = self.data.index
                    self.data.index = self.data["DST_time"]

            logging.debug("Data columns loaded successfully")
            if not self.use_holidays:
                date_helper.do_not_apply_holidays(day_type_var_names[0])

        return self.data
