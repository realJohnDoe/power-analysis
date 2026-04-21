# Tibber Power CLI

Stream real-time power consumption data from Tibber Pulse to CSV.

## Setup

1. Install uv: https://docs.astral.sh/uv/
2. Install dependencies:

   ```bash
   uv sync
   uv pip install -e .
   ```

3. Set your Tibber access token:

   ```bash
   export TIBBER_ACCESS_TOKEN=your-token
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

## Environment Variables

| Variable                 | Description                  | Default                             |
| ------------------------ | ---------------------------- | ----------------------------------- |
| `TIBBER_ACCESS_TOKEN`    | Your Tibber API access token | Required                            |
| `TIBBER_OUTPUT_CSV_PATH` | Output CSV file path         | `~/Desktop/tibber_pulse_stream.csv` |

## Output CSV Columns

- `timestamp` - Reading timestamp
- `accumulated_consumption` - Accumulated consumption today (kWh)
- `accumulated_production` - Accumulated production today (kWh, if you have solar panels)
