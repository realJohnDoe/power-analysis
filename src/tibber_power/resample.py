"""Data resampling with midnight anchor points for handling daily resets."""

import numpy as np
import pandas as pd


def resample_power(df, interval_minutes=15):
    """
    Resample irregular cumulative power data (with a daily reset at midnight)
    to fixed-width intervals whose boundaries align to multiples of
    interval_minutes past noon (12:00, 12:15, …, 23:45, 00:00, 00:15, …).

    The first and last intervals of each day are filled using boundary anchors:
      - Last interval: the day's last reading is held constant to midnight.
      - First interval: the cumulative counter resets to 0 at midnight, so energy
        is interpolated linearly from (midnight, 0) to the first real reading.

    All other intervals are unchanged from the original mask-based interpolation.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain:
          - 'timestamp'       : datetime64[ns] (or parseable), irregular cadence
          - 'cum_production'  : float, cumulative kWh, resets at midnight
          - 'cum_consumption' : float, cumulative kWh, resets at midnight
    interval_minutes : int
        Grid interval in minutes (default 15). Must divide 1440 evenly.

    Returns
    -------
    pd.DataFrame with columns:
        - 'interval_start'      : left boundary of the interval
        - 'interval_end'        : right boundary
        - 'net_production_kwh'  : production minus consumption for the interval
        - 'valid'               : False where data was missing on either side
    """
    # ------------------------------------------------------------------ #
    # 1. Tidy the raw data
    # ------------------------------------------------------------------ #
    df = (
        df
        .copy()
        .sort_values('timestamp')
        .drop_duplicates('timestamp', keep='last')
        .reset_index(drop=True)
    )
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    if df['timestamp'].dt.tz is not None:
        df['timestamp'] = df['timestamp'].dt.tz_localize(None)
    df['date']    = df['timestamp'].dt.date
    df['cum_net'] = df['cum_consumption'] - df['cum_production']

    # ------------------------------------------------------------------ #
    # 2. Build the regular grid anchored to noon so midnight always falls
    #    exactly on a grid boundary.
    # ------------------------------------------------------------------ #
    first_day  = df['timestamp'].iloc[0].normalize()
    last_stamp = df['timestamp'].iloc[-1]

    grid_start = first_day + pd.Timedelta(hours=12)
    while grid_start > df['timestamp'].iloc[0]:
        grid_start -= pd.Timedelta(minutes=interval_minutes)

    grid = pd.date_range(
        start=grid_start,
        end=last_stamp + pd.Timedelta(minutes=interval_minutes),
        freq=f'{interval_minutes}min',
    )
    # Normalise to nanoseconds so .value on pd.Timestamp (always ns) matches.
    grid_int = np.array(grid, dtype='datetime64[ns]').astype('int64')

    # ------------------------------------------------------------------ #
    # 3. Interpolate cumulative net at every grid point, day by day.
    #    Only fill grid points within each day's actual data span — this
    #    preserves NaN for internal gaps and both midnight boundaries.
    # ------------------------------------------------------------------ #
    cum_net_at_grid = np.full(len(grid), np.nan)
    day_data: dict = {}  # date -> (t_int_array, v_array)

    for date, day_df in df.groupby('date'):
        day_df = day_df.sort_values('timestamp')
        t_day = day_df['timestamp'].values.astype('datetime64[ns]').astype('int64')
        v_day = day_df['cum_net'].values.astype(float)
        day_data[date] = (t_day, v_day)

        first_t = day_df['timestamp'].iloc[0]
        last_t  = day_df['timestamp'].iloc[-1]
        mask    = (grid >= first_t) & (grid <= last_t)

        cum_net_at_grid[mask] = np.interp(grid_int[mask], t_day, v_day)

    dates_sorted = sorted(day_data.keys())

    # ------------------------------------------------------------------ #
    # 4. Fill each midnight grid point with day A's last value so that the
    #    last interval of day A gets a valid right endpoint.
    # ------------------------------------------------------------------ #
    for date in dates_sorted:
        t_a, v_a = day_data[date]
        next_midnight = pd.Timestamp(date) + pd.Timedelta(days=1)
        m_idx = np.searchsorted(grid_int, next_midnight.value, side='left')
        on_grid = m_idx < len(grid) and grid_int[m_idx] == next_midnight.value
        if on_grid and np.isnan(cum_net_at_grid[m_idx]):
            cum_net_at_grid[m_idx] = float(v_a[-1])

    # ------------------------------------------------------------------ #
    # 5. Compute per-interval net production (global diff).
    # ------------------------------------------------------------------ #
    net_production = np.diff(cum_net_at_grid)
    has_both = ~np.isnan(cum_net_at_grid[:-1]) & ~np.isnan(cum_net_at_grid[1:])

    # ------------------------------------------------------------------ #
    # 6. Patch the first interval of each day B.
    #    The global diff used day A's midnight value as the left endpoint,
    #    which is wrong — day B's cumulative resets to 0 at midnight.
    #    Recompute net_production[m_idx] = right_val - 0.
    # ------------------------------------------------------------------ #
    for i, date in enumerate(dates_sorted):
        next_midnight = pd.Timestamp(date) + pd.Timedelta(days=1)
        m_idx = np.searchsorted(grid_int, next_midnight.value, side='left')
        if m_idx >= len(grid) or grid_int[m_idx] != next_midnight.value:
            continue
        if m_idx + 1 >= len(grid):
            continue

        next_date = next_midnight.date()
        if next_date not in day_data:
            continue

        t_b, v_b = day_data[next_date]
        right_val = cum_net_at_grid[m_idx + 1]

        if np.isnan(right_val):
            after = t_b > next_midnight.value
            aug_t = np.concatenate([[next_midnight.value], t_b[after]])
            aug_v = np.concatenate([[0.0],                 v_b[after]])
            if len(aug_t) >= 2:
                right_val = float(np.interp(grid_int[m_idx + 1], aug_t, aug_v))

        if not np.isnan(right_val):
            net_production[m_idx] = right_val - 0.0
            has_both[m_idx] = True

    # ------------------------------------------------------------------ #
    # 7. Return
    # ------------------------------------------------------------------ #
    return pd.DataFrame({
        'interval_start':     grid[:-1],
        'interval_end':       grid[1:],
        'net_production_kwh': np.where(has_both, net_production, np.nan),
        'valid':              has_both,
    })
