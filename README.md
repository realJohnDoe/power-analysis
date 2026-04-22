# Tibber Power CLI

Stream real-time power consumption data from Tibber Pulse to CSV.

## Setup

1. Install uv: https://docs.astral.sh/uv/
2. Install dependencies:

   ```bash
   uv sync
   uv pip install -e .
   ```

3. Create a `.env` file with your Tibber access token:

   ```bash
   cp .env.example .env
   # Edit .env and add your token
   ```

   Get your token at: https://developer.tibber.com/

## Usage

### Stream real-time data from Tibber Pulse

For Pulse-only users (without Tibber energy contract), use the stream command to collect real-time data:

```bash
# Stream indefinitely until Ctrl+C
uv run tibber-power

# Stream for 1 hour (3600 seconds)
uv run tibber-power --duration 3600

# Custom output path
uv run tibber-power -o ./my_pulse_data.csv
```

## Environment Variables

| Variable                 | Description                  | Default                             |
| ------------------------ | ---------------------------- | ----------------------------------- |
| `TIBBER_ACCESS_TOKEN`    | Your Tibber API access token | Required                            |
| `TIBBER_OUTPUT_CSV_PATH` | Base output CSV path         | `~/Desktop/tibber_pulse_stream.csv` |

## Monthly CSV Files

The tool automatically creates separate CSV files for each month to prevent files from growing too large:

- `tibber_pulse_stream_2024-01.csv` - January 2024
- `tibber_pulse_stream_2024-02.csv` - February 2024
- etc.

The base filename (set via `TIBBER_OUTPUT_CSV_PATH` or `-o` option) has the month suffix added automatically.

## Output CSV Columns

- `timestamp` - Reading timestamp
- `accumulated_consumption` - Accumulated consumption today (kWh)
- `accumulated_production` - Accumulated production today (kWh, if you have solar panels)
