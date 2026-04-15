import requests, json, gzip, io
import pandas as pd
from typing import List, Dict
import logging

# Configure logging
logger = logging.getLogger(__name__)


def get_by_label(
    label: str, apikey: str, export_to_file: bool = False, output_path: str = None
):
    """Retrieve rate data from OpenEI API using a specific rate label.

    Queries the OpenEI Utility Rate Database API to fetch detailed rate information
    for a specific utility rate identified by its unique label.

    Args:
        label (str): Unique identifier for the utility rate in the OpenEI database.
        apikey (str): OpenEI API key for authentication.

    Returns:
        dict: Rate data structure containing all rate details, or None if the query fails.

    Example:
        >>> rate = get_by_label("590357335457a3ba78cd3b42", "your_api_key")
        >>> print(rate['name'])

    Author:
        Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
    """
    params = {
        "version": "8",
        "format": "json",
        "detail": "full",
        "api_key": apikey,
        "getpage": label,
    }
    response = requests.get("https://api.openei.org/utility_rates", params=params)
    data = json.loads(response.content)
    if "items" not in data:
        logger.warning(
            f"Something is wrong with {label}, query return does not contain 'items'"
        )
        print(data)
        return None
    if len(data["items"]) != 1:
        logger.warning(
            f"Something is wrong with {label}, query return is not a unique item"
        )
        return None

    rate_data = data["items"][0]

    # Export to JSON file if requested
    if export_to_file:
        # Generate filename if not provided
        if output_path is None:
            # Use rate name to create filename, sanitize it for filesystem
            rate_name = rate_data.get("name", label)
            # Replace spaces and special characters with underscores
            safe_name = "".join(
                c if c.isalnum() or c in ("-", "_") else "_" for c in rate_name
            )
            output_path = f"{safe_name}_in_openei_query_format.json"

        try:
            with open(output_path, "w") as f:
                json.dump(rate_data, f, indent=4)
            logger.info(f"Rate data exported to: {output_path}")
            print(f"✓ Rate data exported to: {output_path}")
        except Exception as e:
            logger.error(f"Failed to export rate data to {output_path}: {e}")
            print(f"✗ Failed to export rate data: {e}")

    return rate_data


def rate_df_from_dict(openei_dict_element: List):
    """Convert OpenEI rate structure from nested lists to a pandas DataFrame.

    Transforms the rate structure data from OpenEI (which contains periods and tiers)
    into a flat DataFrame where each row represents a tier with its associated period
    and tier indices.

    Args:
        openei_dict_element (List): Nested list structure from OpenEI containing
            rate periods and tiers.

    Returns:
        pd.DataFrame: DataFrame with columns for rate data, 'period', and 'tier'.

    Note:
        This is an internal helper function called by df_from_openei().

    Author:
        Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
    """
    # for rates - now returns all tiers, not just the first one
    all_tiers = []
    for period_idx, period in enumerate(openei_dict_element):
        for tier_idx, tier in enumerate(period):
            tier_data = tier.copy() if isinstance(tier, dict) else tier
            if isinstance(tier_data, dict):
                tier_data["period"] = period_idx
                tier_data["tier"] = tier_idx
            all_tiers.append(tier_data)

    return pd.DataFrame(all_tiers)


def schedule_matrix_df_from_dict(openei_dict_element: List):
    """Convert OpenEI schedule matrix to a pandas DataFrame.

    Transforms a 12x24 schedule matrix (12 months by 24 hours) from OpenEI
    into a pandas DataFrame with month indices (1-12).

    Args:
        openei_dict_element (List): List of 12 sub-lists, each containing 24 values
            representing hourly data for each month.

    Returns:
        pd.DataFrame: DataFrame with 12 rows (months) and 24 columns (hours).

    Note:
        This is an internal helper function called by df_from_openei().

    Author:
        Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
    """
    # for schedule matrix (12x24)
    temp_df = pd.DataFrame(openei_dict_element, index=range(1, 13))
    return temp_df


def schedule_list_df_from_dict(openei_dict_element: List):
    """Convert OpenEI monthly flat schedule to a pandas DataFrame.

    Transforms a 12-element list (one value per month) from OpenEI into a
    DataFrame with month indices (1-12).

    Args:
        openei_dict_element (List): List of 12 values representing monthly data.

    Returns:
        pd.DataFrame: DataFrame with 12 rows (months) and a 'flat' column.

    Note:
        This is an internal helper function called by df_from_openei().

    Author:
        Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
    """
    # for monthly flat schedule (1x12)
    temp_df = pd.DataFrame(openei_dict_element, columns=["flat"], index=range(1, 13))
    return temp_df


def df_from_openei(openei_dict_element: List):
    """Convert OpenEI data elements to appropriate pandas DataFrame format.

    Automatically detects the type of OpenEI data structure (schedule matrix,
    monthly list, or rate structure) and applies the appropriate conversion.

    Args:
        openei_dict_element (List): OpenEI data structure to convert.

    Returns:
        pd.DataFrame: Converted DataFrame in the appropriate format.

    Note:
        This is an internal helper function called by process_by_keys().

    Author:
        Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
    """
    # wrapper for df from dict defs, automatically infer whether it's a schedule matrix or a rate list
    if not isinstance(openei_dict_element[0], list):
        return schedule_list_df_from_dict(openei_dict_element)
    elif len(openei_dict_element[0]) == 24:
        return schedule_matrix_df_from_dict(openei_dict_element)
    else:
        return rate_df_from_dict(openei_dict_element)


def process_by_keys(openei_data: Dict, keys: List):
    """Process specified keys from OpenEI data dictionary into DataFrames.

    Extracts specified keys from the OpenEI rate data and converts list-type
    values to pandas DataFrames while preserving other data types as-is.

    Args:
        openei_data (Dict): Complete OpenEI rate data dictionary.
        keys (List): List of keys to extract and process.

    Returns:
        dict: Dictionary with processed data (DataFrames for lists, original values otherwise).

    Note:
        This is an internal helper function called by get_processed_data().

    Author:
        Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
    """
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
    """Convert OpenEI rate data into organized DataFrames for analysis.

    Processes raw OpenEI API response data and converts relevant sections
    (demand charges, energy charges, fixed charges) into pandas DataFrames
    for easier manipulation and analysis.

    Args:
        openei_data (Dict): Raw rate data dictionary from OpenEI API
            (typically from get_by_label() or loaded from JSON).

    Returns:
        dict: Nested dictionary containing three main sections:
            - 'demand': Demand charge structures and schedules
            - 'energy': Energy charge structures and schedules
            - 'fixed_charges': Fixed charge information
            Each section contains DataFrames for applicable rate components.

    Example:
        >>> rate_raw = get_by_label("590357335457a3ba78cd3b42", api_key)
        >>> rate_processed = get_processed_data(rate_raw)
        >>> energy_schedule = rate_processed['energy']['energyweekdayschedule']

    Author:
        Jerry Xuechen Lei <xuechen.lei@pnnl.gov>
    """
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

    return data_proc


def get_urdb_labels():
    """
    Retrieves all available rate labels from the OpenEI Utility Rate Database.

    The function downloads the complete database in CSV gzip format and extracts all
    values from the 'label' column.

    Returns:
        list: A list of all rate labels available in the URDB database.
              Returns an empty list if the request fails.

    Example:
        >>> labels = get_urdb_labels()
        >>> print(labels[:5])  # Print first 5 labels
        ['5ca4d1175457a39b23b3d45e', '5ca4d0ac5457a39b23b3d3ec', ...]
    """
    # URL for the URDB database in CSV gzip format
    urdb_csv_url = "https://openei.org/apps/USURDB/download/usurdb.csv.gz"

    try:
        # Download the gzipped CSV file
        response = requests.get(urdb_csv_url, timeout=60)
        response.raise_for_status()  # Raise an error for bad status codes

        # Decompress and read the CSV into a pandas DataFrame
        with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as gz_file:
            df = pd.read_csv(gz_file)

        # Extract the 'label' column values
        if "label" in df.columns:
            return df["label"].tolist()
        else:
            logger.error("Error: 'label' column not found in URDB database")
            return []

    except requests.exceptions.RequestException as e:
        logger.error(f"Error downloading URDB database: {e}")
        return []
    except Exception as e:
        logger.error(f"Error processing URDB database: {e}")
        return []


def get_unique_fixedchargeunits(apikey: str):
    """
    Retrieves all unique 'fixedchargeunits' values from the OpenEI Utility Rate Database.

    This function fetches all rate labels using get_urdb_labels(), then queries each rate
    to extract the 'fixedchargeunits' field, returning only unique values.

    Args:
        apikey (str): OpenEI API key for authentication.

    Returns:
        list: A sorted list of unique 'fixedchargeunits' values found in the database.
              Returns an empty list if no data is available.

    Example:
        >>> api_key = "your_api_key_here"
        >>> unique_units = get_unique_fixedchargeunits(api_key)
        >>> print(unique_units)
        ['$/day', '$/month', '$/year']

    Note:
        This function may take several minutes to complete as it queries thousands of rates.
        Progress is printed every 1000 rates processed.
    """
    # Get all rate labels
    all_labels = get_urdb_labels()

    if not all_labels:
        logger.warning("No labels found in the database")
        return []

    logger.info(f"Found {len(all_labels)} total rates. Starting to query each rate...")

    # Set to store unique values
    unique_units = set()

    # Track progress
    total = len(all_labels)

    # Query each rate and extract fixedchargeunits
    for i, label in enumerate(all_labels):
        try:
            rate_data = get_by_label(label=label, apikey=apikey)

            if rate_data and "fixedchargeunits" in rate_data:
                units = rate_data["fixedchargeunits"]
                if units:  # Only add non-None, non-empty values
                    unique_units.add(units)

            # Print progress every 1000 rates
            if (i + 1) % 1000 == 0:
                logger.info(
                    f"Processed {i + 1}/{total} rates... Found {len(unique_units)} unique units so far"
                )

        except Exception as e:
            # Continue on error but track it
            if (i + 1) % 1000 == 0:
                logger.error(f"Error on label {label}: {e}")
            continue

    logger.info(
        f"Completed! Processed {total} rates and found {len(unique_units)} unique fixedchargeunits values"
    )

    # Return sorted list
    return sorted(list(unique_units))
