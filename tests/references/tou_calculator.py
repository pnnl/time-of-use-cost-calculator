# To add a new cell, type '# %%'
# To add a new markdown cell, type '# %% [markdown]'
# %% [markdown]
# # Pots-processing charge calculation for GEB measure

# %%
import requests
import os
import json, csv
import numpy as np
import pandas as pd
from typing import List, Dict
from IPython.display import display
from datetime import datetime as dt

# from tqdm import tqdm

# own helpers below
from datetimeep import DateTimeEP
from openei_utils import get_processed_data


def calculate_charge(
    case: str,
    epvars,
    # measure: str,
    tou: str = "ashrae",
    tou_path: str = "",
    demand_var_name: str = "Whole Building:Facility Total Purchased Electric Power [W](Hourly)",
    day_type_var_name: str = "Environment:Site Day Type Index [](Hourly)",
    dst_type_var_name: str = "Environment:Site Daylight Saving Time Status [](Hourly)",
    use_dst: bool = False,
    datetime_transform: bool = True,
    holiday: bool = False,
    test: bool = False,
) -> Dict:
    """Calculate energy and demand charges based on TOU rates implemented in OpenEI schema and EP output variables
    NOTE: This calculation assumes simulation is in year 2017 (starts with Sunday)

    Args:
        case (str): case name string, only for output naming
        epvars ([type]): string for path to the csv or csv.gz file; or pd.DataFrame for pandas dataframe including the EP variables
        tou (str, optional): Time-Of-Use rates to be calculated with. If tou_path is empty, rates file needs to be located in the current folder with name as f"{tou}_in_openei_query_format.json". Defaults to "ashrae".
        tou_path (str, optional): Path to the TOU rate json file. Defaults to "", this will lead to TOU rate path being f"{tou}_in_openei_query_format.json"
        demand_var_name (str, optional): EP variable to be used for tariff calculation. Defaults to "Whole Building:Facility Total Purchased Electric Power [W](Hourly)".
        day_type_var_name (str, optional): EP variable to be used for day type. Defaults to "Environment:Site Day Type Index [](Hourly)".
        dst_type_var_name (str, optional): EP variable to be used for daylight saving status. Defaults to "Environment:Site Daylight Saving Time Status [](Hourly)".
        use_dst: (bool, optional): switch of using daylight saving time. Defaults to False.
        datetime_transform (bool, optional): switch of applying datetime_transform within the calculation. Defaults to True.
        holiday (bool, optional): switch of considering holidays as weekends. Defaults to False
        test (bool, optional): true only for dev purpose. Defaults to False.


    Returns:
        Dict: summarized final results key value pairs {"summary": final_results_concise, "detail": final_results}
    """

    # # %% below for dev testing
    # case = "ASHRAE901_OfficeMedium_STD2019_NewYork"
    # epvars = "ASHRAE901_OfficeMedium_STD2019_NewYork_withDSTType.csv"
    # tou = "ashrae"
    # demand_var_name = "Whole Building:Facility Total Purchased Electric Power [W](Hourly)"
    # day_type_var_name = "Environment:Site Day Type Index [](Hourly)"
    # dst_type_var_name = "Environment:Site Daylight Saving Time Status [](Hourly)"
    # datetime_transform = True
    # holiday = False
    # test = False

    # %%
    # resource config
    # specify tou path
    if tou_path == "":
        tou_path = f"{tou}_in_openei_query_format.json"

    # read epvars original dataframe
    if isinstance(epvars, str):
        datetime_transform = True  # enforce datetime transform for string epvars
        # if it is a string path, then deal with it being a csv or a csv.gz
        epvars_strip = epvars.strip()
        if epvars_strip[-3:] == "csv":
            epvars_original = pd.read_csv(epvars)
        elif epvars_strip[-6:] == "csv.gz":
            epvars_original = pd.read_csv(epvars, compression="gzip")
        else:
            print("EEROR: epvars string does not have a .csv or csv.gz postfix")
            return
    elif isinstance(epvars, pd.DataFrame):
        epvars_original = epvars
    else:
        print("ERROR: epvars is neither a string or a pandas DataFrame")
        return

    # cleanup original column name whitespaces
    epvars_original.columns = [one.strip() for one in epvars_original.columns.tolist()]

    # datetime transform
    if datetime_transform:
        # 2017 starts on Sunday and is not a leap year. This aligns with the simulation setting
        dtep = DateTimeEP(epvars_original, year=2017)
        epvars = dtep.transform()
        if use_dst:
            epvars = dtep.add_dst_clocktime(
                dst_type_col=dst_type_var_name, day_type_col=day_type_var_name
            )
            epvars["earth_time"] = epvars.index
            epvars.index = epvars["DST_time"]
    else:
        epvars = epvars_original

    print(f"Start running: {case} <-> {tou} <-> {dt.now()} (with DST? {use_dst})")

    # %%
    # Loading TOU rates...
    with open(tou_path) as f:
        data_tou = json.load(f)
    tou_proc = get_processed_data(data_tou)

    # %%
    # dict for storing final results
    final_results_concise = {"case_name": case, "case_tou": tou}
    final_results = {}

    # %%
    # if not considering holiday, then modify day types
    if not holiday:
        newdaytypes = []
        prev_day = None

        for day_idx, day in epvars.groupby(epvars.index.date):
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
                print("ERROR: previous day should not be None at this stage")

            # assign normal days to a holiday (when it is not Jan 1)
            if prev_day == 7:  # previous day is Saturday
                cur_day = 1
            elif prev_day <= 6:  # previous day is Sunday - Friday
                cur_day = prev_day + 1
            else:
                print(epvars.index[i])
                print("ERROR: two consecutive days are not normal days, weird")
                return
            newdaytypes.extend([cur_day] * len(day))
            prev_day = cur_day

        if len(newdaytypes) != len(epvars):
            print("DEV ERROR: new day types length incorrect")
            return
        epvars[day_type_var_name] = newdaytypes
        # epvars.to_csv(f"{case}_holiday_check.csv")

    #     originaldaytypes = epvars[day_type_var_name].tolist()
    #     for i in range(len(originaldaytypes)):
    #         cur_day = originaldaytypes[i]
    #         if cur_day <= 7:  # a normal day
    #             newdaytypes.append(cur_day)
    #             continue

    #         if i == 0:  # first day is not a normal day
    #             # next_day = originaldaytypes[i + 1]
    #             # if next_day == 1:  # next day is Sunday
    #             #     cur_day = 7
    #             # elif next_day <= 7:  # next day is Monday - Saturday
    #             #     cur_day = next_day - 1
    #             # else:
    #             #     print(epvars.index[i])
    #             #     print("ERROR: two consecutive days are not normal days, weird")
    #             #     return
    #             cur_day = 1  # we know first day is a Sunday
    #             newdaytypes.append(cur_day)
    #             continue

    #         prev_day = newdaytypes[i - 1]
    #         if prev_day == 7:  # previous day is Saturday
    #             cur_day = 1
    #         elif prev_day <= 6:  # previous day is Sunday - Friday
    #             cur_day = prev_day + 1
    #         else:
    #             print(epvars.index[i])
    #             print("ERROR: two consecutive days are not normal days, weird")
    #             return
    #         newdaytypes.append(cur_day)

    #     if len(newdaytypes) != len(originaldaytypes):
    #         print("DEV ERROR: new day types length incorrect")
    #     epvars[day_type_var_name] = newdaytypes
    # epvars.to_csv(f"{case}_holiday_check.csv")

    # %%
    # calculate energy cost
    if "energyratestructure" in tou_proc["energy"]:
        # print(f"Calculating energy charge...")
        timestep = len(epvars.loc[epvars.index[0].date().strftime("%m/%d/%Y")]) / 24
        charge_type = "energy"
        ts_frac = 1 / timestep
        details = []
        for idx, ts in epvars.iterrows():
            day_type = ts[day_type_var_name]

            if (day_type >= 2) and (day_type <= 6):
                weekday_flag = 1
                mat_df = tou_proc[charge_type][f"{charge_type}weekdayschedule"]
            else:  # all other days are using weekend schedule
                weekday_flag = 0
                mat_df = tou_proc[charge_type][f"{charge_type}weekendschedule"]

            price_df = tou_proc[charge_type][f"{charge_type}ratestructure"]
            price_id = mat_df.loc[idx.month, idx.hour]
            if "rate" in price_df.columns:  # some rates has "sell" instead of "rate"
                price = price_df.loc[price_id]["rate"]
            else:
                price = 0

            usage = ts_frac * ts[demand_var_name] / 1000  # in kw

            charge = price * usage
            details.append(
                {
                    "charge": charge,
                    "rate": price,
                    "usage": usage,
                    "ts_frac": ts_frac,
                    "click": 1,
                }
            )

        # %%
        details_df = pd.DataFrame(data=details, index=epvars.index)
        details_monthly = details_df.groupby(by=details_df.index.month).sum()
        details_daily = details_df.groupby(
            by=[details_df.index.month, details_df.index.day]
        ).sum()

        # %%
        # aggregate energy cost
        details_df = pd.DataFrame(data=details, index=epvars.index)
        details_monthly = details_df.groupby(by=details_df.index.month).sum()
        details_daily = details_df.groupby(
            by=[details_df.index.month, details_df.index.day]
        ).sum()

        # for detailed results
        final_results[f"{charge_type}_timestep"] = details_df
        final_results[f"{charge_type}_monthly"] = details_monthly
        final_results[f"{charge_type}_daily"] = details_daily

        # for concise results
        for idx, row in details_monthly.iterrows():
            final_results_concise[f"kwh_{charge_type}_month_{idx:02d}"] = row["usage"]
            final_results_concise[f"charge_{charge_type}_month_{idx:02d}"] = row[
                "charge"
            ]
        final_results_concise[f"kwh_{charge_type}_annual(sum)"] = details_monthly[
            "usage"
        ].sum()
        final_results_concise[f"charge_{charge_type}_annual(sum)"] = details_monthly[
            "charge"
        ].sum()

    # %%
    if "demandratestructure" in tou_proc["demand"]:
        # print("\nProcessing peak demand data...")
        charge_type = "demand"
        details = []
        for idx, ts in epvars.iterrows():
            # first turn peak demand charges to a 8760 sequence
            day_type = ts[day_type_var_name]

            if (day_type >= 2) and (day_type <= 6):
                weekday_flag = 1
                mat_df = tou_proc[charge_type][f"{charge_type}weekdayschedule"]
            else:  # all other days are using weekend schedule
                weekday_flag = 0
                mat_df = tou_proc[charge_type][f"{charge_type}weekendschedule"]

            price_df = tou_proc[charge_type][f"{charge_type}ratestructure"]
            price_id = mat_df.loc[idx.month, idx.hour]
            price = price_df.loc[price_id]["rate"]

            usage = ts[demand_var_name] / 1000  # in kw
            details.append(
                {"rate": price, "rate_id": price_id, "usage": usage, "click": 1}
            )

        details_df = pd.DataFrame(data=details, index=epvars.index)
        final_results[f"peak{charge_type}_timestep"] = details_df
        monthly_totaldemand_df = details_df.groupby(details_df.index.month).max()
        final_results[f"peak{charge_type}_monthlypeakdemand"] = monthly_totaldemand_df
        # print("Done!\n")

        # %%
        for idx, row in monthly_totaldemand_df.iterrows():
            final_results_concise[f"maxkw_{charge_type}_month_{idx:02d}"] = row["usage"]
        final_results_concise[f"maxkw_{charge_type}_annual(max)"] = (
            monthly_totaldemand_df["usage"].max()
        )

        # %%
        # print("Calculating peak demand cost... (Printing month for showing progress)")
        peak_charges = []

        # We have multiple in ASHRAE tou tables, we should combine them into one first
        cur_month = None
        for day_idx, day in details_df.groupby(details_df.index.date):
            if cur_month != day_idx.month:
                # print(day_idx.month, end=", ")
                cur_month = day_idx.month

            in_period = False
            for idx, ts in day.iterrows():
                if not in_period:  # initialize
                    period_start = idx
                    period_stop = idx
                    in_period = True
                    max_use = ts["usage"]
                    rate_id = ts["rate_id"]
                    rate = ts["rate"]
                    continue

                if in_period:
                    if rate_id == ts["rate_id"]:
                        period_stop = idx
                        if ts["usage"] > max_use:
                            max_use = ts["usage"]

                    if rate_id != ts["rate_id"]:
                        peak_charges.append(
                            {
                                "start": period_start,
                                "stop": period_stop,
                                "max_usage": max_use,
                                "rate_id": rate_id,
                                "rate": rate,
                                "charge": max_use * rate,
                            }
                        )

                        # reset to start
                        period_start = idx
                        period_stop = idx
                        max_use = ts["usage"]
                        rate_id = ts["rate_id"]
                        rate = ts["rate"]

            # finally add one period at the end of the day
            peak_charges.append(
                {
                    "start": period_start,
                    "stop": period_stop,
                    "max_usage": max_use,
                    "rate_id": rate_id,
                    "rate": rate,
                    "charge": max_use * rate,
                }
            )
        peak_charge_df = pd.DataFrame(peak_charges)
        # filter out zero charges for check

        peak_charge_df = peak_charge_df[peak_charge_df["charge"] != 0]
        final_results[f"peak{charge_type}_period"] = peak_charge_df
        peak_charge_df.index = peak_charge_df["start"]
        # %%
        peak_charges_by_type = {}
        for rate_type in peak_charge_df["rate_id"].unique():
            rate_type = int(rate_type)
            rate_df = peak_charge_df[peak_charge_df["rate_id"] == rate_type]
            rate_charge_monthly = rate_df.groupby(rate_df.index.month)[
                ["max_usage", "rate_id", "rate", "charge"]
            ].max()
            final_results[f"peak{charge_type}_monthly_rate{rate_type}"] = (
                rate_charge_monthly
            )
            peak_charges_by_type[rate_type] = rate_charge_monthly
        # print("Done!\n")

        # %%
        total_peak_charge = 0
        for k, peak_charge_monthly in peak_charges_by_type.items():
            for i in range(1, 13):
                if i in peak_charge_monthly.index:
                    value = peak_charge_monthly["charge"].loc[i]
                else:
                    value = 0
                final_results_concise[
                    f"charge_peak{charge_type}_rate{k}_month_{i:02d}"
                ] = value
            annual = peak_charge_monthly["charge"].sum()
            final_results_concise[f"charge_peak{charge_type}_rate{k}_annual(sum)"] = (
                annual
            )
            total_peak_charge += annual
        final_results_concise[f"charge_peak{charge_type}_total_annual(sum)"] = (
            total_peak_charge
        )

    # %%
    # demand flat charge
    if "flatdemandstructure" in tou_proc["demand"]:
        # prepare monthly demand data in case peak demand rate does not exist
        charge_type = "demand"
        details = []
        for idx, ts in epvars.iterrows():
            usage = ts[demand_var_name] / 1000  # in kw
            details.append({"usage": usage, "click": 1})
        details_df = pd.DataFrame(data=details, index=epvars.index)
        monthly_totaldemand_df = details_df.groupby(details_df.index.month).max()

        # print("Calculating flat monthly demand charge...")
        details = []
        for idx, mon_demand in monthly_totaldemand_df.iterrows():
            price_id = tou_proc["demand"]["flatdemandmonths"].loc[idx]["flat"]
            price_df = tou_proc["demand"]["flatdemandstructure"]
            price = price_df.loc[price_id]["rate"]
            max_use = mon_demand["usage"]
            details.append(
                {
                    "month": idx,
                    "rate": price,
                    "rate_id": price_id,
                    "max_demand": max_use,
                    "charge": price * max_use,
                }
            )

        flat_charge_df = pd.DataFrame(details)
        flat_charge_df.index = flat_charge_df["month"]
        final_results[f"flat{charge_type}_monthly"] = flat_charge_df
        # print("Done!\n")

        # %%
        for idx, row in flat_charge_df.iterrows():
            final_results_concise[f"charge_{charge_type}flat_month_{idx:02d}"] = row[
                "charge"
            ]
        final_results_concise[f"charge_{charge_type}flat_annual(sum)"] = flat_charge_df[
            "charge"
        ].sum()

    # %%
    final_results_concise = dict(sorted(final_results_concise.items()))

    # %%
    return {"summary": final_results_concise, "detail": final_results}


# %% save function
def save_full_results(results_detail, full_name, folder="tariff_outputs"):
    """Save detailed results to a folder (create if not exist)

    Args:
        results_detail ([type]): calculate_charge(...)["detail"]
        full_name ([type]): case name
        folder (str, optional): results folder. Defaults to 'tariff_outputs'.
    """

    if not os.path.exists(folder):
        os.makedirs(folder)

    for k, v in results_detail.items():
        v.to_csv(f"{folder}/{full_name}_{k}.csv")


# %% Test
if __name__ == "__main__":
    casename = "ASHRAE901_OfficeMedium_STD2022_TampaMeter"
    results_csv = calculate_charge(
        case=casename,
        epvars="ASHRAE901_OfficeMedium_STD2022_TampaMeter.csv",
        tou="ashrae",
        demand_var_name="Whole Building:Facility Total Purchased Electric Power [W](TimeStep)",
        day_type_var_name="Environment:Site Day Type Index [](TimeStep)",
        dst_type_var_name="Environment:Site Daylight Saving Time Status [](TimeStep)",
        use_dst=True,
        datetime_transform=True,
        holiday=False,
        test=False,
    )

    save_full_results(
        results_detail=results_csv["detail"], full_name=casename, folder="devtest"
    )
    rowsdump = {casename: results_csv["summary"]}
    pd.DataFrame.from_dict(rowsdump).T.to_csv(f"devtest/{casename}.csv")

    casename = "ASHRAE901_OfficeMedium_STD2019_NewYork_noDST"
    results_csv = calculate_charge(
        case=casename,
        epvars="ASHRAE901_OfficeMedium_STD2019_NewYork_withDSTType.csv",
        tou="ashrae",
        demand_var_name="Whole Building:Facility Total Purchased Electric Power [W](TimeStep)",
        day_type_var_name="Environment:Site Day Type Index [](TimeStep)",
        dst_type_var_name="Environment:Site Daylight Saving Time Status [](TimeStep)",
        use_dst=False,
        datetime_transform=True,
        holiday=False,
        test=False,
    )

    save_full_results(
        results_detail=results_csv["detail"], full_name=casename, folder="devtest"
    )
    rowsdump = {casename: results_csv["summary"]}
    pd.DataFrame.from_dict(rowsdump).T.to_csv(f"devtest/{casename}.csv")
