"""Utilities for dealing with OpenEI query and processing
- Query: `get_by_label(label: str) -> Dict`
- Processing (dict of multiple types to dict of pd df): `get_processed_data(openei_data: Dict) -> Dict`
"""

import requests
import json, csv
import numpy as np
import pandas as pd
from typing import List, Dict
from IPython.display import display
from tqdm import tqdm


def get_by_label(label: str, apikey: str):
    """Acquire OpenEI json return with label string"""
    params = {
        "version": 3,
        "format": "json",
        "detail": "full",
        "api_key": apikey,
        "getpage": label,
    }
    response = requests.get("https://api.openei.org/utility_rates", params=params)
    data = json.loads(response.content)
    if len(data["items"]) != 1:
        print("Something is wrong, query return is not a unique item")
        return None
    return data["items"][0]


def rate_df_from_dict(openei_dict_element: List):
    """Should not be used directly, supposed to be called only by `df_from_openei()`"""
    # for rates
    i = 0
    temp_dict = {}
    for period in openei_dict_element:
        temp_dict[i] = period[0]
        i += 1
    return pd.DataFrame.from_dict(temp_dict, orient="index")


def schedule_matrix_df_from_dict(openei_dict_element: List):
    """Should not be used directly, supposed to be called only by `df_from_openei()`"""
    # for schedule matrix (12x24)
    temp_df = pd.DataFrame(openei_dict_element, index=range(1, 13))
    return temp_df


def schedule_list_df_from_dict(openei_dict_element: List):
    """Should not be used directly, supposed to be called only by `df_from_openei()`"""
    # for monthly flat schedule (1x12)
    temp_df = pd.DataFrame(openei_dict_element, columns=["flat"], index=range(1, 13))
    return temp_df


def df_from_openei(openei_dict_element: List):
    """Should not be used directly, supposed to be called only by `process_by_keys()`"""
    # wrapper for df from dict defs, automatically infer whether it's a schedule matrix or a rate list
    if not isinstance(openei_dict_element[0], list):
        return schedule_list_df_from_dict(openei_dict_element)
    elif len(openei_dict_element[0]) == 24:
        return schedule_matrix_df_from_dict(openei_dict_element)
    else:
        return rate_df_from_dict(openei_dict_element)


def process_by_keys(openei_data: Dict, keys: List):
    """Should not be used directly, supposed to be called only by `get_processed_data()`"""
    temp_dict = {}
    for key in keys:
        if key in openei_data:  # ignore keys not in data
            if isinstance(openei_data[key], list):
                temp_dict[key] = df_from_openei(openei_data[key])
            else:
                temp_dict[key] = openei_data[
                    key
                ]  # it it is not a list, then add unprocessed data
    return temp_dict


def get_processed_data(openei_data: Dict):
    """Turn a OpenEI query returned json file (load into a dict by `json.load(f)`) into data frames for analysis"""
    data_proc = {
        "demand": {},
        "energy": {},
        "fixed_charges": {},
    }  # redundant, just to show what's in there
    data_proc["demand"] = process_by_keys(
        openei_data,
        [
            "flatdemandstructure",
            "flatdemandmonths",
            "demandratestructure",
            "demandweekdayschedule",
            "demandweekendschedule",
        ],
    )
    data_proc["energy"] = process_by_keys(
        openei_data,
        ["energyratestructure", "energyweekdayschedule", "energyweekendschedule"],
    )
    data_proc["fixed_charges"] = process_by_keys(openei_data, ["fixedmonthlycharge"])

    # for k, v in data_proc.items():
    #     print(f"\n{k}:")
    #     for k_sub, v_sub in v.items():
    #         print(f"\n\t{k_sub}:")
    #         display(v_sub)

    return data_proc
