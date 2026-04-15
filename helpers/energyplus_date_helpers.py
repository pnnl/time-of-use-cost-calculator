import datetime, logging
import pandas as pd

class DateTimeEP:
    """Convert EnergyPlus date time string to python datetime
    
    Author: Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
    """

    def __init__(self, epdf: pd.DataFrame, year=2000):
        """Initialize the DateTimeEP converter.
        
        Author: Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
        
        Args:
            epdf (pd.DataFrame): DataFrame containing EnergyPlus simulation data with 
                a 'Date/Time' column in EnergyPlus format.
            year (int, optional): The year to use for datetime conversion. Defaults to 2000.
        """
        self.year = year
        self.df = epdf.copy(deep=True)

    def transform(self) -> pd.DataFrame:
        """Transform EnergyPlus date/time strings to Python datetime and set as DataFrame index.
                
        Author: Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
        
        This method converts the 'Date/Time' column from EnergyPlus format to Python datetime
        objects, sets them as the DataFrame index, and shifts the index by -1 second to 
        represent mid-hour timestamps for easier processing.
        
        Returns:
            pd.DataFrame: The transformed DataFrame with datetime index.
        """
        self.dt_list = []
        for i, row in self.df.iterrows():
            self.dt_list.append(self.epstr2dt(row["Date/Time"]))
        self.df.index = self.dt_list
        self.df = self.df.shift(
            periods=-1, freq="s"
        )
        self.dt_list = self.df.index.tolist()

        return self.df

    def epstr2dt(self, string: str) -> datetime.datetime:
        """Convert EnergyPlus date/time string to Python datetime object.
        
        The EnergyPlus date string has the format: "01/01  00:40:00" (MM/DD  HH:MM:SS).
        Special handling is provided for midnight (24:00:00), which is converted to 
        00:00:00 of the next day.
                
        Author: Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
        
        Args:
            string (str): EnergyPlus date/time string in format "MM/DD  HH:MM:SS".
        
        Returns:
            datetime.datetime: Python datetime object corresponding to the input string.
        """
        strtup = string.strip().split(sep="  ")
        midnight = False
        if strtup[1] == "24:00:00":
            strtup[1] = "00:00:00"
            midnight = True
        dt = datetime.datetime.strptime(
            f"{strtup[0]}/{self.year}  {strtup[1]}", "%m/%d/%Y  %H:%M:%S"
        )
        if midnight:
            dt = dt + datetime.timedelta(days=1)

        return dt

    def add_dst_clocktime(
        self,
        dst_type_col: str = "Environment:Site Daylight Saving Time Status [](Hourly)",
        day_type_col: str = "Environment:Site Day Type Index [](Hourly)",
        dst_dt_col: str = "DST_time",
    ) -> pd.DataFrame:
        """Add daylight saving time column (python datetime), can deal with timestep timeseries as well.
        
        This method adjusts timestamps to account for daylight saving time (DST) transitions.
        During spring forward, one hour is skipped. During fall back, one hour is repeated.
        The day type column can also be modified accordingly to reflect the correct day types
        after DST adjustments.
                
        Author: Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
        
        Args:
            dst_type_col (str, optional): Name of the column containing DST status 
                (1 for DST active, 0 for standard time). 
                Defaults to "Environment:Site Daylight Saving Time Status [](Hourly)".
            day_type_col (str, optional): Name of the column containing day type indices.
                Set to None if day type adjustment is not wanted.
                Defaults to "Environment:Site Day Type Index [](Hourly)".
            dst_dt_col (str, optional): Name of the new column to store DST-adjusted datetimes.
                Defaults to "DST_time".
        
        Returns:
            pd.DataFrame: The DataFrame with added DST-adjusted datetime column and 
                optionally updated day type column.
        """
        timestep = int(
            len(self.df.loc[self.df.index[0].date().strftime("%m/%d/%Y")]) / 24
        )
        dst_dt_list = []
        day_type_list = []
        if day_type_col is not None:
            old_day_type_list = self.df[day_type_col].tolist()
        in_dst = False
        dst_action = "nothing"
        dtlist_i = 0
        timestep_counter = None
        for i, row in self.df.iterrows():
            if dst_action == "nothing":
                # dst switch detection
                dst_status = row[dst_type_col]
                if dst_status == 1 and in_dst == False:
                    dst_action = "skip next hour"
                    timestep_counter = timestep
                if dst_status == 0 and in_dst == True:
                    dst_action = "repeat next hour"
                    timestep_counter = timestep
            else:
                # check timestep counter
                if timestep_counter == 1:  # dst change completed when countdown to 1
                    # dst action
                    if dst_action == "skip next hour":
                        dtlist_i += timestep
                        in_dst = True
                    if dst_action == "repeat next hour":
                        dtlist_i -= timestep
                        in_dst = False
                    dst_action = "nothing"
                    timestep_counter = None
                else:
                    timestep_counter -= 1
            dst_dt_list.append(self.dt_list[dtlist_i])
            if day_type_col is not None:
                day_type_list.append(old_day_type_list[dtlist_i])
            dtlist_i += 1
        self.df[dst_dt_col] = dst_dt_list
        if day_type_col is not None:
            self.df[day_type_col] = day_type_list
        return self.df
    
    def do_not_apply_holidays(self, day_type_var_name: str) -> pd.DataFrame:
        """Remove holiday designations from the day type column, converting holidays to regular weekdays.
        
        This method processes the day type column to replace holiday values (>7) with normal
        weekday values (1-7) based on the progression of days. It maintains the correct
        weekday sequence when holidays are encountered.
                
        Author: Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
        
        Args:
            epvars (pd.DataFrame): DataFrame containing EnergyPlus variables with datetime index.
            day_type_var_name (str): Name of the column containing day type indices.
                Values 1-7 represent Sunday-Saturday, values >7 represent holidays.
        
        Returns:
            pd.DataFrame: The DataFrame with updated day type column where holidays are
                converted to normal weekdays, or None if an error occurs.
        
        Raises:
            Logs error messages if inconsistencies are detected in the day type sequence.
        """
                
        newdaytypes = []
        prev_day = None

        for day_idx, day in self.df.groupby(self.df.index.date):
            ori_day = day.iloc[0][day_type_var_name]

            if ori_day <= 7:  # a normal day
                cur_day = ori_day
                newdaytypes.extend([cur_day] * len(day))
                prev_day = cur_day
                continue

            if prev_day is None:  #  only run when the first day is not a normal day
                cur_day = 1  # we know first day is a Sunday
                newdaytypes.extend([cur_day] * len(day))
                prev_day = cur_day
                continue

            if prev_day is None:
                logging.error("Previous day should not be None at this stage")

            # assign normal days to a holiday (when it is not Jan 1)
            if prev_day == 7:  # previous day is Saturday
                cur_day = 1
            elif prev_day <= 6:  # previous day is Sunday - Friday
                cur_day = prev_day + 1
            else:
                logging.error(f"Two consecutive days are not normal days at index {day_idx}, unexpected behavior")
                return self.df
            newdaytypes.extend([cur_day] * len(day))
            prev_day = cur_day

        if len(newdaytypes) != len(self.df):
            logging.error(f"New day types length ({len(newdaytypes)}) does not match DataFrame length ({len(self.df)})")
            return self.df
        self.df[day_type_var_name] = newdaytypes
        return self.df
