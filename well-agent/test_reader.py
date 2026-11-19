from pathlib import Path
from src.results.reader import load_run, check_data
from src.results.analysis import summarize_periods
from src.results.analysis import summarize_transition
from src.results.analysis import summarize_interval_volumes
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

file_path = Path.home() / "OLGA_data" / "case1_obhod.tpl"
df, catalog = load_run(file_path)
print("Размер таблицы:")
print(df.shape)
print("\nПервые 5 строк:")
print(df.head())
print("\nКаталог каналов:")
print(catalog.head())
print("\nПроверка качества данных:")
print(check_data(df))
print("\nВСЕ КАНАЛЫ OLGA:")

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

print("\nНАЗВАНИЯ ВЕТОК:")

print(sorted(catalog["branch"].unique()))

print("\nКАНАЛЫ ДАВЛЕНИЯ И РАСХОДА:")

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
print("\nСРАВНЕНИЕ РЕЖИМОВ:")
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
            48,
            color="black",
            linestyle="--",
            label="Переключение"
        )

        ax.axvspan(48, 50, alpha=0.12)

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
    plt.show()

plot_olga(
    analysis_data,
    catalog,
    branches,
    "olga_analysis.png"
)
plot_olga(
    analysis_data,
    catalog,
    branches,
    "olga_transition_zoom.png",
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


print("\nПРОВЕРКА ACCLIQ И ИНТЕГРАЛА QLT:")

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

    volume_scale = max(abs(delta_acc), abs(integrated_flow))

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
    "interval_volumes.csv",
    index=False,
    encoding="utf-8-sig"
)
print("\nТаблица сохранена в interval_volumes.csv")





inlet_branches = [
    "AGZU 4 - MBSNU",
    "AGZU 60,7 - AGZU 4",
    "AGZU 6 - AGZU 4"
]
outlet_branch = "MBSNU - AGZU 2"
balance_records = []
for period_name, (start_h, end_h) in volume_periods.items():

    period_data = interval_results[
        interval_results["period"] == period_name
    ]

    inlet_volume = period_data.loc[
        period_data["branch"].isin(inlet_branches),
        "integral_QLT_m3"
    ].sum()

    outlet_volume = period_data.loc[
        period_data["branch"] == outlet_branch,
        "integral_QLT_m3"
    ].sum()

    duration = end_h - start_h

    balance_records.append({
        "period": period_name,
        "inlet_volume_m3": inlet_volume,
        "outlet_volume_m3": outlet_volume,
        "difference_m3": inlet_volume - outlet_volume,
        "inlet_mean_m3_h": inlet_volume / duration,
        "outlet_mean_m3_h": outlet_volume / duration
    })

network_balance = pd.DataFrame(balance_records)
print("\nПРЕДВАРИТЕЛЬНЫЙ БАЛАНС СИСТЕМЫ:")
print(network_balance.round(4).to_string(index=False))

