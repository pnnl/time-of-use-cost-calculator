import pandas as pd
import datetime


class DateTimeEP:
    """convert EnergyPlus date time string to python datetime"""

    def __init__(self, epdf: pd.DataFrame, year=2000):
        self.year = year
        self.df = epdf.copy(deep=True)

    def transform(self) -> pd.DataFrame:
        self.dt_list = []
        for i, row in self.df.iterrows():
            self.dt_list.append(self.epstr2dt(row["Date/Time"]))
        self.df.index = self.dt_list
        self.df = self.df.shift(
            periods=-1, freq="s"
        )  # shift index to mid hour for easy processing
        self.dt_list = self.df.index.tolist()

        return self.df

    def epstr2dt(self, string: str) -> datetime.datetime:
        """The ep date string haves the format: "01/01  00:40:00" """
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
    ) -> datetime.datetime:
        """Add daylight saving time column (python datetime), can deal with timestep timeseries as well.
        Day type column can also be modified accordingly. If not wanted, set day_type_col to `None`.
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


def main():
    df = pd.read_csv("ASHRAE901_OfficeMedium_STD2019_NewYork_withDSTType.csv")

    old_cols = df.columns.tolist()
    new_cols = [one.strip() for one in old_cols]
    df.columns = new_cols

    dtep = DateTimeEP(df)
    dtep.transform()
    new_df = dtep.add_dst_clocktime()

    new_df.to_csv("testoutput_datetimeep.csv")


if __name__ == "__main__":
    main()
