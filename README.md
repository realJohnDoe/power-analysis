# Tibber Power CLI

Download power consumption data from the Tibber API.

## Setup

1. Install uv: https://docs.astral.sh/uv/
2. Install dependencies:

   ```bash
   uv sync
   uv pip install -e .
   ```

3. Set your Tibber access token:

   ```bash
   # Option 1: Environment variable
   export TIBBER_ACCESS_TOKEN=your-token

   # Option 2: Provide via CLI
   uv run tibber-power download --token YOUR_TOKEN_HERE
   ```

   Get your token at: https://developer.tibber.com/

## Usage

### Stream real-time data from Tibber Pulse

For Pulse-only users (without Tibber energy contract), use the stream command to collect real-time data:

```bash
# Stream indefinitely until Ctrl+C
uv run tibber-power stream

# Stream for 1 hour (3600 seconds)
uv run tibber-power stream --duration 3600

# Custom output path
uv run tibber-power stream -o ./my_pulse_data.csv
```

### Download billed consumption data

If you have a Tibber energy contract, download historical billed data:

```bash
# Hourly data for last 24 hours
uv run tibber-power download

# Daily data for last 30 days
uv run tibber-power download --resolution DAILY --last 30 -o ./power.csv
```

### List homes

```bash
uv run tibber-power list-homes
```

## Resolutions (for billed data)

- `HOURLY` - Hourly consumption
- `DAILY` - Daily consumption
- `WEEKLY` - Weekly consumption
- `MONTHLY` - Monthly consumption
- `YEARLY` - Yearly consumption

## Output CSV Columns

### Billed consumption (download command)

- `period_start` - Start of measurement period
- `period_end` - End of measurement period
- `consumption_kwh` - Energy consumption in kWh
- `unit_price` - Price per unit
- `unit_price_vat` - VAT portion of unit price
- `total_cost` - Total cost for the period
- `exported_at` - Timestamp when data was exported

### Pulse stream (stream command)

- `timestamp` - Reading timestamp
- `accumulated_consumption` - Accumulated consumption today (kWh)
- `accumulated_production` - Accumulated production today (kWh, if you have solar panels)
