from pathlib import Path
from src.results.reader import load_run, check_data
from src.results.analysis import summarize_periods
from src.results.analysis import summarize_transition
from src.results.analysis import summarize_interval_volumes
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import json

file_path = Path.home() / "OLGA_data" / "case1_obhod.tpl"
df, catalog = load_run(file_path)
run_dir = Path("results") / "manual_case1_obhod"
run_dir.mkdir(parents=True, exist_ok=True)

EVENT_TIME_H = 48.0
TRANSITION_DURATION_S = 60.0

TRANSITION_END_H = (
    EVENT_TIME_H + TRANSITION_DURATION_S / 3600
)
hol_catalog = catalog[
    catalog["variable"] == "HOL"
]
time_s = df["time_s"].to_numpy(dtype=float)
sample_hours = [0, 47, 48, 50, 52.5, 56, 96]
hol_records = []
for _, channel in hol_catalog.iterrows():

    column = channel["column"]

    hol = pd.to_numeric(
        df[column],
        errors="coerce"
    ).to_numpy(dtype=float)

    record = {
        "branch": channel["branch"],
        "HOL_min": np.nanmin(hol),
        "HOL_max": np.nanmax(hol),
        "HOL_mean": np.nanmean(hol)
    }

    for hour in sample_hours:
        record[f"HOL_{hour:g}h"] = np.interp(
            hour * 3600,
            time_s,
            hol
        )

    hol_records.append(record)

hol_summary = pd.DataFrame(hol_records)

print("\nИЗМЕНЕНИЕ HOL ПО ВЕТВЯМ:")
print(hol_summary.round(5).to_string(index=False))


print("\nВсе типы переменных:")
print(catalog["variable"].value_counts().to_string())

print("\nПоиск каналов запаса жидкости:")
mask = catalog["variable"].astype(str).str.contains(
    r"HOL|HOLD|VOL|INVENT|MASS|LEVEL",
    case=False,
    regex=True,
    na=False
)
if "description" in catalog.columns:
    mask |= catalog["description"].astype(str).str.contains(
        r"holdup|hold-up|liquid volume|liquid inventory|liquid content",
        case=False,
        regex=True,
        na=False
    )
columns = [
    "branch", "variable", "location_type",
    "pipe", "nr", "unit", "description", "column"
]
columns = [c for c in columns if c in catalog.columns]
print(catalog.loc[mask, columns].to_string(index=False))

print("Размер таблицы:")
print(df.shape)
print("\nПервые 5 строк:")
print(df.head())
print("\nКаталог каналов:")
print(catalog.head())
print("\nПроверка качества данных:")
print(check_data(df))

# Анализ временной сетки OLGA
time_values = pd.to_numeric(
    df["time_s"],
    errors="coerce"
).to_numpy(dtype=float)

intervals = np.diff(time_values)

if (
    not np.isfinite(time_values).all()
    or np.any(intervals <= 0)
):
    print("Ошибка: временной ряд некорректен")

else:
    print("\nАнализ временной сетки")

    print(f"Количество интервалов: {len(intervals)}")
    print(f"Минимальный шаг: {np.min(intervals):.6f} с")
    print(f"Максимальный шаг: {np.max(intervals):.6f} с")
    print(f"Средний шаг: {np.mean(intervals):.6f} с")
    print(f"Медианный шаг: {np.median(intervals):.6f} с")

    print("\nПрцентили временного шага")
    for percentile in [50, 90, 95, 99]:
        value = np.percentile(intervals, percentile)
        print(f"{percentile}%: {value:.6f} с")
    print(
        "\nОтношение максимального шага "
        "к медианному:",
        round(np.max(intervals) / np.median(intervals), 3)
    )
    # Находим 10 самых больших интервалов
    largest_indices = np.argsort(intervals)[-10:][::-1]
    largest_intervals = pd.DataFrame({
        "start_time_s": time_values[largest_indices],
        "end_time_s": time_values[largest_indices + 1],
        "interval_s": intervals[largest_indices]
    })

    print("\n10 Самых больших интервалов:")
    print(largest_intervals.to_string(index=False))



print("\nВсе каналы OLGA:")
print(
    catalog[
        [
            "variable",
            "location_type",
            "branch",
            "pipe",
            "nr",
            "unit",
            "description"
        ]
    ].to_string(index=False)
)

print("\nНазвание веток:")

print(sorted(catalog["branch"].unique()))

print("\nКаналы давления и расхода:")

important = catalog[
    catalog["variable"].isin(["PT", "QLT", "QG", "ACCLIQ"])
]

print(
    important[
        ["column", "variable", "branch", "unit", "description"]
    ].to_string(index=False)
)


branches = [
    "BYPASS",
    "SEPARATOR TUBE",
    "PUMPTUBE",
    "MBSNU - AGZU 2",
    "MBSNU TUBE",
    "AGZU 4 - MBSNU"
]

variables = ["PT", "QLT", "QG", "GT", "GG"]

selected = catalog[
    catalog["branch"].isin(branches)
    & catalog["variable"].isin(variables)
]

print("\nВЫБРАННЫЕ КАНАЛЫ:")
print(
    selected[
        ["branch", "variable", "column", "unit"]
    ].to_string(index=False)
)

analysis_data = df[["time_s"] + selected["column"].tolist()].copy()

analysis_data["time_h"] = analysis_data["time_s"] / 3600

for _, row in selected.iterrows():
    if row["variable"] == "PT":
        analysis_data[row["column"] + "_MPa"] = (
            analysis_data[row["column"]] / 1_000_000
        )

    elif row["variable"] == "QLT":
        analysis_data[row["column"] + "_m3_h"] = (
            analysis_data[row["column"]] * 3600
        )

print("\nПЕРВЫЕ СТРОКИ АНАЛИТИЧЕСКОЙ ТАБЛИЦЫ:")
print(analysis_data.head())

print("\nРазмер аналитической таблицы:")
print(analysis_data.shape)

periods = {
    "До переключения": (47, 48),
    "Переходный процесс": (48, 50),
    "После переключения": (90, 96)
}
summary = summarize_periods(
    analysis_data,
    catalog,
    branches,
    periods
)
print("\nСравнение режимов:")
print(summary.round(4).to_string(index=False))

def plot_olga(data, catalog, branches, filename, xlim=None):

    fig, axes = plt.subplots(
        2, 1,
        figsize=(14, 9),
        sharex=True
    )

    for branch in branches:
        q_channel = catalog.loc[
            (catalog["branch"] == branch)
            & (catalog["variable"] == "QLT"),
            "column"
        ].iloc[0]
        p_channel = catalog.loc[
            (catalog["branch"] == branch)
            & (catalog["variable"] == "PT"),
            "column"
        ].iloc[0]
        axes[0].plot(
            data["time_h"],
            data[q_channel] * 3600,
            label=branch
        )
        axes[1].plot(
            data["time_h"],
            data[p_channel] / 1_000_000,
            label=branch
        )

    for ax in axes:
        ax.axvline(
            EVENT_TIME_H,
            color="black",
            linestyle="--",
            label="Начало переключения"
        )
        ax.axvline(
            TRANSITION_END_H,
            color="red",
            linestyle=":",
            label="Конец переключения (60 с)"
        )
        ax.axvspan(
            EVENT_TIME_H,
            TRANSITION_END_H,
            alpha=0.12,
            label="Переходный интервал"
        )

        ax.grid(True)
        ax.legend(fontsize=8)

        if xlim is not None:
            ax.set_xlim(xlim)

    axes[0].set_ylabel("Расход жидкости, м³/ч")
    axes[0].set_title("Изменение расхода жидкости")
    axes[1].set_ylabel("Давление, МПа")
    axes[1].set_xlabel("Время, ч")
    axes[1].set_title("Изменение давления")
    fig.suptitle("Результаты моделирования OLGA", fontsize=14)
    plt.tight_layout()
    plt.savefig(filename, dpi=200, bbox_inches="tight")
    plt.close(fig)

plot_olga(
    analysis_data,
    catalog,
    branches,
    run_dir / "olga_analysis.png"
)
plot_olga(
    analysis_data,
    catalog,
    branches,
    run_dir / "olga_transition_zoom.png",
    xlim=(46, 56)
)

transition_results = summarize_transition(
    analysis_data,
    catalog,
    branches
)

print("\nХарактеристики переходного процесса:")

print(
    transition_results.round(4).to_string(index=False)
)


print("\nКаналы ACCLIQ И QLT:")
balance_channels = catalog[
    catalog["variable"].isin(["ACCLIQ", "QLT"])
]

print(
    balance_channels[
        [
            "branch",
            "variable",
            "location_type",
            "pipe",
            "nr",
            "unit",
            "column"
        ]
    ].to_string(index=False)
)


print("\nПроверка ACCLIQ и интеграла QLT:")

pairs = balance_channels.pivot_table(
    index=["branch", "location_type", "pipe", "nr"],
    columns="variable",
    values="column",
    aggfunc="first"
).reset_index()

records = []

for _, pair in pairs.iterrows():

    if pd.isna(pair.get("ACCLIQ")) or pd.isna(pair.get("QLT")):
        continue

    acc_column = pair["ACCLIQ"]
    q_column = pair["QLT"]

    time = df["time_s"].to_numpy(dtype=float)
    flow = df[q_column].to_numpy(dtype=float)
    accumulated = df[acc_column].to_numpy(dtype=float)

    delta_acc = accumulated[-1] - accumulated[0]

    integrated_flow = np.trapezoid(flow, x=time)

    difference = delta_acc - integrated_flow


    volume_scale = max(
        abs(delta_acc),
        abs(integrated_flow)
    )

    if volume_scale < 0.01:
        relative_error = np.nan
    else:
        relative_error = (
            abs(difference) / volume_scale * 100
        )

    records.append({
        "branch": pair["branch"],
        "delta_ACCLIQ_m3": delta_acc,
        "integral_QLT_m3": integrated_flow,
        "difference_m3": difference,
        "relative_error_pct": relative_error
    })


balance_check = pd.DataFrame(records)

print(balance_check.round(4).to_string(index=False))

volume_periods = {
    "До переключения": (47, 48),
    "Переходный процесс": (48, 52.5),
    "После стабилизации": (52.5, 56)
}
interval_results = summarize_interval_volumes(
    df,
    catalog,
    volume_periods
)
print("\nОбъемы жидкости по временным интервалам:")

print(
    interval_results.round(4).to_string(index=False)
)
print(
    "\nКоличество проверенных ветвей:",
    interval_results["branch"].nunique()
)
interval_results.to_csv(
    run_dir / "interval_volumes.csv",
    index=False,
    encoding="utf-8-sig"
)
print("\nТаблица сохранена в interval_volumes.csv")


boundary_signs = {
    "AGZU 4 - MBSNU": 1,
    "AGZU 60,7 - AGZU 4": 1,
    "AGZU 6 - AGZU 4": 1,
    "PUMP TUBE - COPY": -1,
    "SEPARATOR TUBE": -1,
    "MBSNU - AGZU 2": -1,
    "PUMP TUBE - COPY (2)": -1
}

def get_channel_column(branch, variable):

    matches = catalog.loc[
        (catalog["branch"] == branch)
        & (catalog["variable"] == variable),
        "column"
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Не найден канал {variable}: {branch}"
        )

    return matches.iloc[0]

def integrate_values(values, start_h, end_h):
    time_s = df["time_s"].to_numpy(dtype=float)
    values = np.asarray(values, dtype=float)

    start_s = start_h * 3600
    end_s = end_h * 3600
    mask = (time_s > start_s) & (time_s < end_s)
    interval_time = np.concatenate((
        [start_s],
        time_s[mask],
        [end_s]
    ))
    interval_values = np.concatenate((
        [np.interp(start_s, time_s, values)],
        values[mask],
        [np.interp(end_s, time_s, values)]
    ))
    return float(np.trapezoid(
        interval_values,
        x=interval_time
    ))

balance_records = []
for period_name, (start_h, end_h) in volume_periods.items():

    period_data = interval_results[
        interval_results["period"] == period_name
    ]
    signed_volumes = {}
    signed_masses = {}
    for branch, direction in boundary_signs.items():
        volume = period_data.loc[
            period_data["branch"] == branch,
            "integral_QLT_m3"
        ]
        if len(volume) != 1:
            raise ValueError(
                f"Некорректный канал QLT: {branch}"
            )

        signed_volumes[branch] = (
            direction * float(volume.iloc[0])
        )
        gt_column = get_channel_column(branch, "GT")
        gg_column = get_channel_column(branch, "GG")
        liquid_mass_flow = (
            df[gt_column].to_numpy(dtype=float)
            - df[gg_column].to_numpy(dtype=float)
        )
        signed_masses[branch] = (
            direction * integrate_values(
                liquid_mass_flow,
                start_h,
                end_h
            )
        )

    inlet_volume = sum(
        max(value, 0.0)
        for value in signed_volumes.values()
    )
    outlet_volume = sum(
        max(-value, 0.0)
        for value in signed_volumes.values()
    )
    inlet_mass = sum(
        max(value, 0.0)
        for value in signed_masses.values()
    )
    outlet_mass = sum(
        max(-value, 0.0)
        for value in signed_masses.values()
    )
    duration = end_h - start_h
    balance_records.append({
        "period": period_name,
        "inlet_volume_m3": inlet_volume,
        "outlet_volume_m3": outlet_volume,
        "volume_difference_m3": inlet_volume - outlet_volume,
        "inlet_mass_kg": inlet_mass,
        "outlet_mass_kg": outlet_mass,
        "mass_difference_kg": inlet_mass - outlet_mass,
        "inlet_mean_m3_h": inlet_volume / duration,
        "outlet_mean_m3_h": outlet_volume / duration
    })

network_balance = pd.DataFrame(balance_records)
print("\nСравнение граничных потоков:")
print(network_balance.round(4).to_string(index=False))




def dataframe_records(frame):
    return json.loads(
        frame.to_json(orient="records")
    )

metrics = {
    "schema_version": "1.0",
    "run_type": "manual_reference",
    "source_artifact": file_path.name,
    "time_range_s": {
        "start": float(df["time_s"].iloc[0]),
        "end": float(df["time_s"].iloc[-1]),
        "points": int(len(df))
    },
    "event": {
        "event_time_s": 172800,
        "transition_duration_s": 60,
        "transition_end_s": 172860
    },
    "period_summary": dataframe_records(summary),
    "transition_summary": dataframe_records(
        transition_results
    ),
    "interval_volumes": dataframe_records(
        interval_results
    ),
    "preliminary_network_balance": dataframe_records(
        network_balance
    ),
    "engineering_assessment": "NOT_ASSESSED",
    "limitations": [
        "Нет результатов автоматического запуска для сравнения.",
        "Полный динамический баланс не подтвержден: "
        "отсутствуют данные об изменении запаса жидкости.",
        "Инженерные допуски пока не согласованы."
    ]
}

with open(
    run_dir / "metrics.json",
    "w",
    encoding="utf-8"
) as file:
    json.dump(
        metrics,
        file,
        ensure_ascii=False,
        indent=4
    )

comparison = pd.DataFrame([{
    "metric": "manual_vs_automatic",
    "manual_value": None,
    "automatic_value": None,
    "absolute_error": None,
    "relative_error_pct": None,
    "assessment": "NOT_ASSESSED",
    "reason": "Нет результатов автоматического запуска"
}])

comparison.to_csv(
    run_dir / "comparison.csv",
    index=False,
    encoding="utf-8-sig"
)

network_balance.to_csv(
    run_dir / "network_balance_preliminary.csv",
    index=False,
    encoding="utf-8-sig"
)

print("\nСОХРАНЕНИЕ РЕЗУЛЬТАТОВ:")
print(f"Папка: {run_dir.resolve()}")
for artifact in sorted(run_dir.iterdir()):
    print(artifact.name)
print("\nФормирование результатов завершено.")

print(
    "\nВНИМАНИЕ: изменение запаса жидкости "
    "в данном расчёте не учитывается."
)
