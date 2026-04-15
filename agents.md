# Energy Cost Calculator - AI Agent Guide

This document provides comprehensive information for AI agents to understand and work with this energy cost calculator repository.

## Repository Overview

This is a Python-based energy cost calculator that computes electricity costs based on utility rate structures and building energy simulation data. It supports complex rate structures including time-of-use rates, tiered pricing, demand charges, and fixed charges.

## Project Structure

```
repo/
├── energy_cost_calculator.py      # Main calculator implementation
├── helpers/                        # Helper modules
│   ├── data_loader.py             # Load and preprocess energy data
│   ├── energyplus_date_helpers.py # Date/time utilities for EnergyPlus data
│   └── openei_helpers.py          # OpenEI API utilities for rate data
├── tests/                          # Test suite
│   ├── test_energy_cost_calculator.py    # Unit tests (22 tests)
│   ├── test_calculator_comparison.py     # Comparison tests with reference
│   ├── data/sample_simulation_output/    # Sample CSV data files
│   └── references/                       # Reference implementation
│       ├── tou_calculator.py            # Legacy calculator for comparison
│       ├── datetimeep.py                # Date utilities for reference impl
│       └── openei_utils.py              # OpenEI utils for reference impl
├── sample_rates/                   # Sample rate JSON files
├── dev/                           # Development notebooks
└── pyproject.toml                 # Poetry dependency management
```

## Core Components

### 1. EnergyCostCalculator (energy_cost_calculator.py)

**Purpose**: Main class that calculates energy costs based on rate structures and usage data.

**Key Methods**:
- `__init__()` - Initialize with rate data and usage data
- `get_total_cost()` - Calculate total energy cost (energy + demand + fixed)
- `calculate_energy_cost()` - Calculate energy charges (time-of-use, tiered)
- `calculate_demand_cost()` - Calculate demand charges (peak, flat, TOU)
- `calculate_fixed_charge_cost()` - Calculate fixed monthly/daily/yearly charges
- `get_summary()` - Get detailed cost breakdown and statistics

**Important Implementation Details**:
- Uses `len(pd.unique())` instead of `.nunique()` on numpy arrays (fixed AttributeError)
- Supports unit conversion (W → kW for demand, W → kWh for energy)
- Handles variable timesteps (15min, hourly, etc.)
- Validates units between data and rate structures

**Rate Structure Support**:
- Energy: Time-of-use (TOU) rates with tiered pricing
- Demand: Flat demand, TOU demand, coincident demand (not implemented)
- Fixed: Daily, monthly, yearly fixed charges
- Adjustments: Rate adjustments can be applied

### 2. DataForCostCalculation (helpers/data_loader.py)

**Purpose**: Load and preprocess energy simulation data from various sources.

**Supported Data Sources**:
- EnergyPlus CSV output files
- Custom CSV formats

**Key Features**:
- Converts timestamps to pandas DatetimeIndex
- Adds day type classification (weekday/weekend/holiday)
- Handles daylight saving time
- Validates required columns

**Usage Example**:
```python
from helpers.data_loader import DataForCostCalculation

data_loader = DataForCostCalculation(
    path_to_data_file="simulation_output.csv",
    data_source="EnergyPlus",
    year=2017,
    use_holidays=False
)
data = data_loader.data  # Returns preprocessed DataFrame
```

### 3. OpenEI Helpers (helpers/openei_helpers.py)

**Purpose**: Fetch and process utility rate data from OpenEI URDB API.

**Key Functions**:
- `get_by_label(label, apikey)` - Fetch rate by label/ID
- `get_processed_data(rate_data)` - Convert rate to pandas DataFrames
- `get_urdb_labels()` - Get list of all available rates

**Rate Data Structure** (after processing):
```python
{
    'energy': {
        'energyratestructure': DataFrame,  # Rates by period/tier
        'energyweekdayschedule': DataFrame,  # 12x24 schedule
        'energyweekendschedule': DataFrame   # 12x24 schedule
    },
    'demand': {
        'flatdemandstructure': DataFrame,
        'demandratestructure': DataFrame,
        'demandweekdayschedule': DataFrame,
        'demandweekendschedule': DataFrame
    }
}
```

## Running the Calculator

### Basic Usage

```python
from energy_cost_calculator import EnergyCostCalculator
from helpers.data_loader import DataForCostCalculation

# Load energy data
data_loader = DataForCostCalculation(
    path_to_data_file="path/to/data.csv",
    data_source="EnergyPlus",
    year=2017
)

# Initialize calculator
calculator = EnergyCostCalculator(
    rate_json_path="path/to/rate.json",  # OR rate_label="label_id"
    data=data_loader.data,
    include_energy_cost=True,
    include_demand_cost=True,
    include_fixed_cost=True,
    number_of_meters=1,
    electricity_demand_var_name="Electricity:Facility [W](Hourly)"
)

# Calculate costs
total_cost = calculator.get_total_cost()
summary = calculator.get_summary()
```

### Command Line Usage

The comparison test can be run from the repo root:
```bash
poetry run python tests/test_calculator_comparison.py
```

## Testing

### Unit Tests (22 tests)

Run with pytest from repo root:
```bash
poetry run pytest tests/test_energy_cost_calculator.py -v
```

**Test Coverage**:
- Unit conversion (power, energy)
- Unit validation (demand, energy)
- Rate loading (JSON, API)
- Fixed charges (daily, monthly, yearly)
- Number of meters validation
- Summary calculations
- Variable timestep handling
- Error handling (missing data, missing columns)

### Comparison Tests

Compares new implementation against reference `tou_calculator`:
```bash
poetry run python tests/test_calculator_comparison.py
```

**What it does**:
1. Runs both calculators on sample data
2. Compares results (must match within $0.01 tolerance)
3. Validates energy, demand, and total costs
4. Saves detailed results to JSON

**Current Status**: All tests passing ✓
- 2/2 combinations pass
- Perfect match between calculators ($0.00 difference)

## Development Setup

### Requirements
- Python 3.10+
- Poetry for dependency management

### Installation

```bash
# Install dependencies
poetry install

# Activate virtual environment
poetry shell

# Run tests
poetry run pytest tests/test_energy_cost_calculator.py -v
```

### Key Dependencies
- pandas: Data manipulation
- numpy: Numerical operations
- requests: OpenEI API calls
- ipython: Notebook support
- tqdm: Progress bars (for reference implementation)
- pytest: Testing framework
- black: Code formatting

### Code Quality

All code must pass:
```bash
# Black formatting check
poetry run black --check .

# Run all tests
poetry run pytest tests/test_energy_cost_calculator.py -v
```

## Common Issues & Solutions

### 1. AttributeError: 'numpy.ndarray' object has no attribute 'nunique'

**Fixed**: Use `len(pd.unique(array))` instead of `array.nunique()`

Affected lines:
- `energy_cost_calculator.py:538, 545, 552, 563` (fixed charge calculation)
- `energy_cost_calculator.py:820-821` (summary calculation)

### 2. Import Error: "No module named 'IPython'" or "No module named 'tqdm'"

**Solution**: Install dev dependencies
```bash
poetry add ipython tqdm --group dev
```

### 3. Test Comparison Fails: "No CSV files found"

**Issue**: Running from wrong directory
**Solution**: Always run from repo root:
```bash
cd /path/to/repo
poetry run python tests/test_calculator_comparison.py
```

### 4. Rate Data Issues

**Missing rate fields**: Some rates don't have all structures (e.g., no demand rates)
**Solution**: Check if field exists before accessing:
```python
if "demand" in rate:
    rate_demand = rate["demand"]
else:
    logging.error("Demand rate data not found")
    return 0
```

## Data Format Requirements

### Input CSV (EnergyPlus)

Required columns:
- `Date/Time` - Timestamp in EnergyPlus format
- `Electricity:Facility [W](Hourly)` - Power demand in watts
- Auto-generated: `Environment:Site Day Type Index [](Hourly)` - Day type (weekday=2-6)

### Rate JSON (OpenEI Format)

Key fields:
- `energyratestructure` - Energy rate tiers/periods
- `energyweekdayschedule` - Weekday TOU schedule (12 months × 24 hours)
- `energyweekendschedule` - Weekend TOU schedule
- `demandratestructure` - Demand rate tiers (optional)
- `flatdemandstructure` - Flat demand rates (optional)
- `fixedchargefirstmeter` - Fixed monthly charge (optional)

## Algorithm Overview

### Energy Cost Calculation

1. **Load rate schedule** (weekday/weekend based on day type)
2. **For each timestep**:
   - Get rate period from schedule (based on month, hour)
   - Get cumulative monthly kWh
   - Find appropriate tier based on cumulative usage
   - Get rate for (period, tier)
   - Apply rate adjustment if enabled
   - Calculate: `charge = usage_kWh × rate`
3. **Sum all timestep charges**

### Demand Cost Calculation

**Flat Demand** (monthly peak):
1. Find maximum demand (kW) for each month
2. Get flat demand rate for that month
3. Charge = max_demand × rate (once per month)

**Time-of-Use Demand** (peak per period):
1. Assign rate period to each timestep
2. For each month:
   - For each TOU period:
     - Find maximum demand in that period
     - Charge = max_demand × period_rate
3. Add to flat demand (they stack)

### Fixed Cost Calculation

Based on `fixedchargeunits`:
- `$/day`: `days × rate × number_of_meters`
- `$/month`: `months × rate × number_of_meters`
- `$/year`: `years × rate × number_of_meters`

## API Reference

### EnergyCostCalculator

```python
class EnergyCostCalculator:
    def __init__(
        self,
        rate_label=None,                    # OpenEI rate label
        rate_json_path=None,                # Path to local rate JSON
        data=None,                          # pandas DataFrame with usage
        include_demand_cost=False,          # Calculate demand charges
        include_energy_cost=False,          # Calculate energy charges
        include_fixed_cost=False,           # Calculate fixed charges
        number_of_meters=1,                 # Number of meters (≥1)
        electricity_demand_var_name=None,   # Column name for demand
        add_adjustment_to_rate=True         # Apply rate adjustments
    )
    
    def get_total_cost(self, add_adjustment_to_rate=True) -> float
    def calculate_energy_cost(self, add_adjustment_to_rate=True) -> float
    def calculate_demand_cost(self, add_adjustment_to_rate=True) -> float
    def calculate_fixed_charge_cost(self) -> float
    def get_summary(self) -> dict
```

### DataForCostCalculation

```python
class DataForCostCalculation:
    def __init__(
        self,
        path_to_data_file,     # Path to CSV file
        data_source,           # "EnergyPlus" or other
        year,                  # Year for datetime conversion
        use_holidays=False     # Use US federal holidays
    )
    
    # Properties:
    self.data  # pandas DataFrame with processed data
```

## GitHub Actions CI/CD

Workflow runs on push/PR:
1. Run unit tests (`pytest tests/test_energy_cost_calculator.py`)
2. Run comparison tests (`python tests/test_calculator_comparison.py`)
3. Check code formatting (`black --check .`)
4. Upload test results as artifacts

All tests must pass for CI to succeed.

## Future Enhancements

Potential improvements:
1. Support coincident demand charges
2. Add more data source types (CSV variations, databases)
3. Support seasonal rates
4. Add rate optimization features
5. Web API wrapper
6. Visualization tools for cost breakdown

## Contact & Support

This calculator is maintained as part of PNNL energy modeling projects.

For issues:
1. Check this agents.md file first
2. Review test files for usage examples
3. Check existing test coverage for similar scenarios

---

Last Updated: April 15, 2026
Version: 1.0.0
Python: 3.10+
