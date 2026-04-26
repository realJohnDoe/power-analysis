"""Data resampling with midnight anchor points for handling daily resets."""

import numpy as np
import pandas as pd


def add_midnight_anchors(df):
    """
    For each midnight boundary between consecutive days, interpolate a synthetic
    data point from each day's cumulative series and inject it at ±1 second from
    midnight. This ensures the midnight grid boundary is always bracketed by data
    from the correct day on each side.

    df must have columns: 'timestamp', 'date', 'cum_net'
    Returns a list of dicts with the same columns plus 'synthetic': True.
    """
    rows = []
    dates = sorted(df['date'].unique())

    for i in range(len(dates) - 1):
        day_a = df[df['date'] == dates[i]]      # day ending at midnight
        day_b = df[df['date'] == dates[i + 1]]  # day starting after midnight

        midnight = pd.Timestamp(dates[i + 1])   # 00:00:00 of the next calendar day

        t_a = day_a['timestamp'].values.astype('int64')
        v_a = day_a['cum_net'].values

        t_b = day_b['timestamp'].values.astype('int64')
        v_b = day_b['cum_net'].values

        # Interpolate each day's cumulative series toward midnight.
        # left=np.nan / right=np.nan means we don't extrapolate beyond the data;
        # if the day's data doesn't reach midnight the anchor is simply omitted.
        net_a = float(np.interp(midnight.value, t_a, v_a, left=np.nan, right=np.nan))
        net_b = float(np.interp(midnight.value, t_b, v_b, left=np.nan, right=np.nan))

        # Place day A's anchor one second BEFORE midnight (still day A's series)
        if not np.isnan(net_a):
            rows.append({
                'timestamp': midnight - pd.Timedelta(seconds=1),
                'date':      dates[i],
                'cum_net':   net_a,
                'synthetic': True,
            })

        # Place day B's anchor one second AFTER midnight (day B's series, which
        # has reset to 0, so net_b is already in day B's cumulative units)
        if not np.isnan(net_b):
            rows.append({
                'timestamp': midnight + pd.Timedelta(seconds=1),
                'date':      dates[i + 1],
                'cum_net':   net_b,
                'synthetic': True,
            })

    return rows


def resample_power(df, interval_minutes=15):
    """
    Resample irregular cumulative power data (with a daily reset at midnight)
    to fixed-width intervals whose boundaries align to multiples of
    interval_minutes past noon (12:00, 12:15, …, 23:45, 00:00, 00:15, …).

    Parameters
    ----------
    df : pd.DataFrame
        Must contain:
          - 'timestamp'       : datetime64[ns] (or parseable), irregular cadence
          - 'cum_production'  : float, cumulative kWh, resets at midnight
          - 'cum_consumption' : float, cumulative kWh, resets at midnight
    interval_minutes : int
        Grid interval in minutes (default 15). Must divide 60 evenly.

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
    df['date']      = df['timestamp'].dt.date
    df['cum_net']   = df['cum_consumption'] - df['cum_production']

    # ------------------------------------------------------------------ #
    # 2. Inject synthetic midnight anchor points
    # ------------------------------------------------------------------ #
    synthetic_rows = add_midnight_anchors(df)
    if synthetic_rows:
        df_synth = pd.DataFrame(synthetic_rows)
        df = (
            pd.concat([df[['timestamp', 'date', 'cum_net']], df_synth],
                      ignore_index=True)
            .sort_values(['date', 'timestamp'])
            .reset_index(drop=True)
        )

    # ------------------------------------------------------------------ #
    # 3. Build the regular grid anchored to noon
    #    Noon is chosen so that midnight always falls exactly on a boundary
    #    (noon + N * interval_minutes == midnight for any integer N when
    #    interval_minutes divides 720), while the ±1-second synthetic points
    #    sit safely on opposite sides of that boundary.
    # ------------------------------------------------------------------ #
    first_day  = df['timestamp'].iloc[0].normalize()   # 00:00 of first day
    last_stamp = df['timestamp'].iloc[-1]

    grid_start = first_day + pd.Timedelta(hours=12)    # noon of first day
    # Step back to cover data that starts before noon on the first day
    while grid_start > df['timestamp'].iloc[0]:
        grid_start -= pd.Timedelta(minutes=interval_minutes)

    grid = pd.date_range(
        start=grid_start,
        end=last_stamp + pd.Timedelta(minutes=interval_minutes),
        freq=f'{interval_minutes}min',
    )

    # ------------------------------------------------------------------ #
    # 4. Interpolate cumulative net at every grid point, day by day
    # ------------------------------------------------------------------ #
    cum_net_at_grid = np.full(len(grid), np.nan)

    for date, day_df in df.groupby('date'):
        day_df = day_df.sort_values('timestamp')
        t_day  = day_df['timestamp'].values.astype('int64')
        v_day  = day_df['cum_net'].values

        # Only fill grid points that lie within this day's data span
        first_t = day_df['timestamp'].iloc[0]
        last_t  = day_df['timestamp'].iloc[-1]
        mask    = (grid >= first_t) & (grid <= last_t)

        cum_net_at_grid[mask] = np.interp(
            grid[mask].values.astype('int64'),
            t_day,
            v_day,
        )

    # ------------------------------------------------------------------ #
    # 5. Compute per-interval net production
    # ------------------------------------------------------------------ #
    net_production = np.diff(cum_net_at_grid)
    interval_start = grid[:-1]
    interval_end   = grid[1:]

    # Valid if both endpoints have data (not NaN)
    has_both_endpoints = (
        ~np.isnan(cum_net_at_grid[:-1]) &
        ~np.isnan(cum_net_at_grid[1:])
    )

    return pd.DataFrame({
        'interval_start':     interval_start,
        'interval_end':       interval_end,
        'net_production_kwh': np.where(has_both_endpoints, net_production, np.nan),
        'valid':              has_both_endpoints,
    })
