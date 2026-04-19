# Tibber Power CLI

Download power consumption data from the Tibber API.

## Setup

1. Install uv: https://docs.astral.sh/uv/
2. Install dependencies:
   ```bash
   uv sync
   ```

3. Set your Tibber access token:
   ```bash
   # Option 1: Environment variable
   export TIBBER_ACCESS_TOKEN=your-token

   # Option 2: .env file (copy from .env.example)
   cp .env.example .env
   # Then edit .env with your token
   ```

   Get your token at: https://developer.tibber.com/

## Usage

### Download consumption data

```bash
# Default: hourly data for last 168 hours (1 week) to ~/Desktop
uv run tibber-power download

# Custom options
uv run tibber-power download --resolution DAILY --last 30 -o ./power.csv

# Specify token inline
uv run tibber-power download --token YOUR_TOKEN_HERE
```

### List homes

```bash
uv run tibber-power list-homes
```

## Resolutions

- `HOURLY` - Hourly consumption
- `DAILY` - Daily consumption
- `WEEKLY` - Weekly consumption
- `MONTHLY` - Monthly consumption
- `YEARLY` - Yearly consumption

## Output CSV Columns

- `period_start` - Start of measurement period
- `period_end` - End of measurement period
- `consumption_kwh` - Energy consumption in kWh
- `unit` - Unit of measurement (kWh)
- `unit_price` - Price per unit
- `unit_price_vat` - VAT portion of unit price
- `total_cost` - Total cost for the period
- `exported_at` - Timestamp when data was exported
- `resolution` - Data resolution used
