import logging
import pandas as pd

from helpers.energyplus_date_helpers import DateTimeEP


DAY_TYPE_FROM_WEEKDAY = {0: 2, 1: 3, 2: 4, 3: 5, 4: 6, 5: 7, 6: 1}
DAY_TYPE_COL = "Environment:Site Day Type Index [](Hourly)"


class DataForCostCalculation:
    def __init__(
        self,
        path_to_data_file,
        data_source="EnergyPlus",
        year=2000,
        use_holidays=False,
        skip_rows=0,
        datetime_col=None,
    ):
        self.path_to_data_file = path_to_data_file
        self.data_source = data_source
        self.use_holidays = use_holidays
        self.skip_rows = skip_rows
        self.datetime_col = datetime_col
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
            if len(dst_type_var_names) > 0 and len(day_type_var_names) > 0:
                self.data = date_helper.add_dst_clocktime(
                    day_type_col=day_type_var_names[0],
                    dst_type_col=dst_type_var_names[0],
                )

            logging.debug("Data columns loaded successfully")
            if not self.use_holidays:
                date_helper.do_not_apply_holidays(day_type_var_names[0])

        elif self.data_source.lower() == "csv":
            if self.datetime_col is None:
                logging.error(
                    "A datetime column name must be provided via datetime_col when data_source='csv'."
                )
                return None
            if self.datetime_col not in self.data.columns:
                logging.error(
                    f"Datetime column '{self.datetime_col}' not found in data."
                )
                return None

            self.data[self.datetime_col] = pd.to_datetime(self.data[self.datetime_col])
            self.data = self.data.set_index(self.datetime_col)
            self.data.index = self.data.index.map(
                lambda ts: ts.replace(year=year) if ts.year != year else ts
            )

            self.data[DAY_TYPE_COL] = self.data.index.weekday.map(DAY_TYPE_FROM_WEEKDAY)

            if self.use_holidays:
                try:
                    import holidays as holidays_lib

                    country_holidays = holidays_lib.country_holidays("US", years=year)
                    for date, _ in self.data.groupby(self.data.index.date):
                        if date in country_holidays:
                            self.data.loc[
                                self.data.index.date == date, DAY_TYPE_COL
                            ] = 8

                except ImportError:
                    logging.warning(
                        "The 'holidays' package is not installed; holiday detection skipped. "
                        "Install it with: pip install holidays"
                    )

        return self.data
