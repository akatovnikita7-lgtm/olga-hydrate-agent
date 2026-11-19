from pathlib import Path
import re
import shlex
import numpy as np
import pandas as pd

def make_column_name(variable, location_type, branch, pipe, nr):
    parts = [variable, location_type, branch, pipe, f"NR{nr}"]
    cleaned = [
        re.sub(r"[^A-Za-z0-9]+", "_", part).strip("_").upper()
        for part in parts
    ]
    return "__".join(cleaned)


def load_run(path: str | Path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")

    with path.open("r", encoding="ascii") as file:
        lines = file.readlines()

    catalog_index = next(
        i for i, line in enumerate(lines)
        if line.strip() == "CATALOG"
    )
    catalog_size = int(lines[catalog_index + 1].strip())
    catalog_lines = lines[
        catalog_index + 2: catalog_index + 2 + catalog_size
    ]
    catalog = []
    for index, line in enumerate(catalog_lines):

        fields = shlex.split(line.strip())

        variable = fields[0]
        location_type = fields[1].rstrip(":")
        branch = fields[3]
        pipe = fields[5]
        nr = fields[7]
        unit = fields[8]
        description = fields[9] if len(fields) > 9 else ""

        column = make_column_name(
            variable,
            location_type,
            branch,
            pipe,
            nr
        )

        catalog.append({
            "column": column,
            "variable": variable,
            "location_type": location_type,
            "branch": branch,
            "pipe": pipe,
            "nr": nr,
            "unit": unit,
            "description": description
        })

    catalog_df = pd.DataFrame(catalog)

    time_series_index = next(
        i for i, line in enumerate(lines)
        if line.strip().startswith("TIME SERIES")
    )
    columns = ["time_s"] + catalog_df["column"].tolist()

    data = pd.read_csv(
        path,
        sep=r"\s+",
        skiprows=time_series_index + 1,
        header=None,
        names=columns,
        engine="c"
    )
    if data.shape[1] != len(columns):
        raise ValueError("Количество столбцов не совпадает с каталогом")
    return data, catalog_df

def check_data(data):
    time = data["time_s"]
    intervals = time.diff().dropna()
    return {
        "rows": len(data),
        "columns": len(data.columns),
        "start_time": time.iloc[0],
        "end_time": time.iloc[-1],
        "monotonic": time.is_monotonic_increasing,
        "duplicates": time.duplicated().sum(),
        "missing": data.isna().sum().sum(),
        "finite": np.isfinite(data.to_numpy()).all(),
        "mean_interval": intervals.mean(),
        "min_interval": intervals.min(),
        "max_interval": intervals.max()
    }