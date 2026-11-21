import pandas as pd
import numpy as np


def summarize_periods(data, catalog, branches, periods):
    records = []
    for period_name, (start_h, end_h) in periods.items():
        mask = (
            (data["time_h"] >= start_h)
            & (data["time_h"] < end_h)
        )
        if not mask.any():
            raise ValueError(f"Нет данных за период {period_name}")
        period_data = data.loc[mask]
        for branch in branches:
            record = {
                "period": period_name,
                "branch": branch,
                "points": len(period_data)
            }

            for variable, factor, unit in [
                ("PT", 1_000_000, "MPa"),
                ("QLT", 1 / 3600, "m3_h")
            ]:
                channel = catalog[
                    (catalog["branch"] == branch)
                    & (catalog["variable"] == variable)
                ]
                if len(channel) != 1:
                    raise ValueError(
                        f"Ожидался один канал {variable} "
                        f"для ветви {branch}"
                    )
                column = channel.iloc[0]["column"]
                if variable == "PT":
                    values = period_data[column] / factor
                else:
                    values = period_data[column] * 3600

                record[f"{variable}_mean_{unit}"] = values.mean()
                record[f"{variable}_min_{unit}"] = values.min()
                record[f"{variable}_max_{unit}"] = values.max()

            records.append(record)

    return pd.DataFrame(records)


def summarize_transition(
    data,
    catalog,
    branches,
    start_h=48,
    end_h=56
):
    transition = data[
        (data["time_h"] >= start_h)
        & (data["time_h"] <= end_h)
    ]

    if transition.empty:
        raise ValueError("Нет данных в выбранном интервале")

    records = []

    for branch in branches:

        channels = {}

        for variable in ["PT", "QLT"]:
            matches = catalog.loc[
                (catalog["branch"] == branch)
                & (catalog["variable"] == variable),
                "column"
            ]

            if len(matches) != 1:
                raise ValueError(
                    f"Не найден единственный канал {variable}: {branch}"
                )

            channels[variable] = matches.iloc[0]

        pressure = transition[channels["PT"]] / 1_000_000
        flow = transition[channels["QLT"]] * 3600

        p_max_index = pressure.idxmax()
        q_max_index = flow.idxmax()
        q_min_index = flow.idxmin()

        p_stable = find_stabilization_time(
            data,
            channels["PT"],
            scale=1 / 1_000_000,
            absolute_tolerance=0.005
        )

        q_stable = find_stabilization_time(
            data,
            channels["QLT"],
            scale=3600,
            absolute_tolerance=0.1
        )

        records.append({
            "branch": branch,

            "max_pressure_MPa": pressure.max(),
            "max_pressure_time_h": transition.loc[
                p_max_index, "time_h"
            ],

            "max_flow_m3_h": flow.max(),
            "max_flow_time_h": transition.loc[
                q_max_index, "time_h"
            ],

            "min_flow_m3_h": flow.min(),
            "min_flow_time_h": transition.loc[
                q_min_index, "time_h"
            ],

            "pressure_stabilization_h": p_stable["time_h"],
            "flow_stabilization_h": q_stable["time_h"]
        })

    return pd.DataFrame(records)



def find_stabilization_time(
    data,
    column,
    scale,
    start_h=48,
    reference_start_h=90,
    reference_end_h=96,
    relative_tolerance=0.01,
    absolute_tolerance=0.1
):
    time = data["time_h"].to_numpy(dtype=float)
    values = data[column].to_numpy(dtype=float) * scale

    reference_mask = (
        (time >= reference_start_h)
        & (time <= reference_end_h)
    )

    if not reference_mask.any():
        raise ValueError("Нет данных для определения режима")

    reference_value = values[reference_mask].mean()

    tolerance = max(
        abs(reference_value) * relative_tolerance,
        absolute_tolerance
    )

    candidates = np.flatnonzero(time >= start_h)

    # Suffix maximum avoids the previous quadratic scan of every remaining row.
    deviations = np.abs(values - reference_value)
    suffix_max = np.maximum.accumulate(deviations[::-1])[::-1]
    stable = candidates[suffix_max[candidates] <= tolerance]
    if stable.size:
        return {
            "time_h": float(time[stable[0]]),
            "reference": float(reference_value),
            "tolerance": float(tolerance)
        }

    return {
        "time_h": None,
        "reference": float(reference_value),
        "tolerance": float(tolerance)
    }


def summarize_interval_volumes(
    data,
    catalog,
    periods,
    branches=None,
    near_zero_m3=0.01
):
    time = data["time_s"].to_numpy(dtype=float)

    if len(time) < 2 or not np.all(np.diff(time) > 0):
        raise ValueError("Время должно строго возрастать")

    keys = ["branch", "location_type", "pipe", "nr"]

    channels = catalog[
        catalog["variable"].isin(["ACCLIQ", "QLT"])
    ]

    records = []

    for key, group in channels.groupby(
        keys, dropna=False, sort=False
    ):
        branch, location_type, pipe, nr = key

        if branches is not None and branch not in branches:
            continue

        acc_matches = group.loc[
            group["variable"] == "ACCLIQ", "column"
        ]

        qlt_matches = group.loc[
            group["variable"] == "QLT", "column"
        ]

        if len(acc_matches) != 1 or len(qlt_matches) != 1:
            raise ValueError(
                f"Некорректная пара каналов: {branch}"
            )

        acc_column = acc_matches.iloc[0]
        qlt_column = qlt_matches.iloc[0]

        accumulated = data[acc_column].to_numpy(dtype=float)
        flow = data[qlt_column].to_numpy(dtype=float)

        if not np.isfinite(accumulated).all():
            raise ValueError(f"Ошибка данных ACCLIQ: {branch}")

        if not np.isfinite(flow).all():
            raise ValueError(f"Ошибка данных QLT: {branch}")

        for period_name, (start_h, end_h) in periods.items():

            start_s = start_h * 3600
            end_s = end_h * 3600

            if end_s <= start_s:
                raise ValueError(f"Некорректный период: {period_name}")

            if start_s < time[0] or end_s > time[-1]:
                raise ValueError(f"Период вне диапазона данных: {period_name}")

            mask = (time > start_s) & (time < end_s)

            interval_time = np.concatenate((
                [start_s],
                time[mask],
                [end_s]
            ))

            interval_flow = np.concatenate((
                [np.interp(start_s, time, flow)],
                flow[mask],
                [np.interp(end_s, time, flow)]
            ))

            acc_start = np.interp(start_s, time, accumulated)
            acc_end = np.interp(end_s, time, accumulated)

            delta_acc = acc_end - acc_start

            integral_qlt = np.trapezoid(
                interval_flow,
                x=interval_time
            )

            difference = delta_acc - integral_qlt

            volume_scale = max(
                abs(delta_acc),
                abs(integral_qlt)
            )

            if volume_scale < near_zero_m3:
                relative_error = np.nan
            else:
                relative_error = (
                    abs(difference) / volume_scale * 100
                )

            mean_flow = (
                integral_qlt / (end_s - start_s) * 3600
            )

            records.append({
                "branch": branch,
                "period": period_name,
                "start_h": start_h,
                "end_h": end_h,
                "delta_ACCLIQ_m3": delta_acc,
                "integral_QLT_m3": integral_qlt,
                "difference_m3": difference,
                "relative_error_pct": relative_error,
                "mean_flow_m3_h": mean_flow
            })

    if not records:
        raise ValueError("Не найдены пары ACCLIQ и QLT")

    return pd.DataFrame(records)



