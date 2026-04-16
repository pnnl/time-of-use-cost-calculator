# Energy Cost Calculator

A Python-based energy cost calculator that calculates energy costs from building simulation outputs (e.g., EnergyPlus) using utility rate structures from the OpenEI database or local JSON files. It provides cost calculations for complex rate structures including time-of-use energy rates, tiered pricing, flat and TOU demand charges, and fixed monthly fees.

## Features

- Time-of-use (TOU) energy rates
- Tiered pricing structures
- Flat demand charges
- TOU demand charges
- Fixed charges (daily, monthly, yearly)
- Multiple meter support
- Unit validation and conversion (W, kW, MW)
- Variable timestep support
- Fuel adjustments (not yet implemented)
- Coincident demand charges (not yet implemented)

## Requirements

- Python 3.10 or higher
- Poetry (for dependency management)

## Installation

1. Install Poetry (if not already installed):
```bash
curl -sSL https://install.python-poetry.org | python3 -
```

2. Install project dependencies:
```bash
poetry install
```

3. For development dependencies (includes Black formatter):
```bash
poetry install --with dev
```

## Usage

### Basic Usage with Poetry

```bash
poetry run python energy_cost_calculator.py \
  --data-file tests/data/sample_simulation_output/ASHRAE901_OfficeMedium_STD2022_TampaMeter.csv \
  --data-source energyplus \
  --year 2023 \
  --rate-label "5ed5ada75457a39b23d4b03d" \
  --number-of-meters 1 \
  --demand-var "Electricity:Facility [W](Hourly)"
```

### Usage without Poetry

If you prefer not to use Poetry, install dependencies with pip:

```bash
pip install pandas numpy requests
```

Then run the calculator directly:

```bash
python energy_cost_calculator.py \
  --data-file tests/data/sample_simulation_output/ASHRAE901_OfficeMedium_STD2022_TampaMeter.csv \
  --data-source energyplus \
  --year 2023 \
  --rate-label "5ed5ada75457a39b23d4b03d" \
  --number-of-meters 1 \
  --demand-var "Electricity:Facility [W](Hourly)"
```

### Using a Local JSON Rate File

Instead of fetching rates from OpenEI API, you can use a local JSON rate file:

```bash
python energy_cost_calculator.py \
  --data-file tests/data/sample_simulation_output/ASHRAE901_OfficeMedium_STD2022_TampaMeter.csv \
  --data-source energyplus \
  --year 2023 \
  --rate-file sample_rates/ashrae_in_openei_query_format.json \
  --number-of-meters 1 \
  --demand-var "Electricity:Facility [W](Hourly)"
```

Note: Use `--rate-file` instead of `--rate-label` when providing a local JSON file.

### Exporting Detailed Results

To export detailed cost calculation results to CSV files, use the `--export-detailed` flag:

```bash
python energy_cost_calculator.py   --data-file tests/data/sample_simulation_output/ASHRAE901_OfficeMedium_STD2022_TampaMeter.csv   --data-source energyplus   --year 2023   --rate-file sample_rates/ashrae_in_openei_query_format.json   --number-of-meters 1   --demand-var "Electricity:Facility [W](Hourly)"   --export-detailed
```

This will create the following CSV files in the `outputs/` folder:
- `case_timestep_charges.csv` - Hourly charge details
- `case_energy_monthly.csv` - Monthly energy aggregations
- `case_energy_daily.csv` - Daily energy aggregations
- `case_demand_monthly.csv` - Monthly demand aggregations
- `case_summary.csv` - Overall cost summary
- `case_full_data.csv` - Complete dataset with all calculations

**Customize output location and file names:**

```bash
python energy_cost_calculator.py   --data-file tests/data/sample_simulation_output/ASHRAE901_OfficeMedium_STD2022_TampaMeter.csv   --data-source energyplus   --year 2023   --rate-file sample_rates/ashrae_in_openei_query_format.json   --number-of-meters 1   --demand-var "Electricity:Facility [W](Hourly)"   --export-detailed   --output-folder results   --case-name my_building_2023
```

### Running Tests

```bash
cd tests
poetry run python test_calculator_comparison.py
```

## Development

### Code Formatting

The project uses Black for code formatting with a line length of 88 characters.

**Format all code:**
```bash
poetry run black .
```

**Check formatting without making changes:**
```bash
poetry run black --check --diff .
```

**Note:** The reference file `tests/references/tou_calculator.py` is excluded from formatting to maintain its original state.

### Project Structure

```
repo/
├── energy_cost_calculator.py          # Main calculator
├── helpers/                            # Helper modules
│   ├── data_loader.py
│   ├── energyplus_date_helpers.py
│   └── openei_helpers.py
├── sample_rates/                       # Sample rate files
│   ├── ashrae_in_openei_query_format.json
│   └── coned_in_openei_query_format.json
└── tests/                              # Test files
    ├── test_calculator_comparison.py
    ├── data/sample_simulation_output/
    └── references/tou_calculator.py
```

### Problematic Rates
- https://apps.openei.org/USURDB/rate/view/539f6adaec4f024411ec94db#3__Energy: Tier 4 shows max usage units as kWh/kW... so hours?