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
    errors = []
    warnings = []

    if data.empty:
        return {
            "valid": False,
            "errors": ["Таблица пустая"],
            "warnings": [],
            "rows": 0,
            "columns": 0
        }

    if "time_s" not in data.columns:
        return {
            "valid": False,
            "errors": ["Отсутствует столбец time_s"],
            "warnings": [],
            "rows": len(data),
            "columns": len(data.columns)
        }

    time = pd.to_numeric(data["time_s"], errors="coerce")
    time_values = time.to_numpy(dtype=float)

    invalid_time = int(time.isna().sum())
    finite_time = bool(np.isfinite(time_values).all())
    if invalid_time > 0:
        errors.append(
            f"Некорректных значений времени: {invalid_time}"
        )
    if not finite_time:
        errors.append("Время содержит бесконечные значения")
    negative_time = bool(
        np.any(
            np.isfinite(time_values)
            & (time_values < 0)
        )
    )
    if negative_time:
        errors.append("Отрицательное время моделирования")
    duplicates = int(time.duplicated().sum())
    if duplicates > 0:
        errors.append(
            f"Обнаружено повторяющихся временных отметок: {duplicates}"
        )
    intervals = np.diff(time_values)
    monotonic = bool(
    len(time_values) >= 2
    and finite_time
    and np.all(intervals > 0)
    )
    if len(time_values) < 2:
        errors.append("Недостаточно точек для анализа")
    elif finite_time and not monotonic:
        errors.append("Время не является строго возрастающим")
    missing = int(data.isna().sum().sum())
    if missing > 0:
        errors.append(
            f"Обнаружено пропущенных значений: {missing}"
        )

    for column in data.columns:
        if column == "time_s":
            continue
        converted = pd.to_numeric(
            data[column],
            errors="coerce"
        )
        invalid_mask = (
            data[column].notna()
            & converted.isna()
        )
        invalid_count = int(invalid_mask.sum())

        if invalid_count > 0:
            errors.append(
                f"Нечисловых значений в столбце "
                f"{column}: {invalid_count}"
            )

    numeric_data = data.apply(
        pd.to_numeric,
        errors="coerce"
    )
    numeric_values = numeric_data.to_numpy(dtype=float)
    finite = bool(
        numeric_values.size > 0
        and np.isfinite(numeric_values).all()
    )
    if not finite:
        errors.append(
            "Числовые данные содержат NaN или бесконечности"
        )

    if finite_time and len(intervals) > 0:
        mean_interval = float(np.mean(intervals))
        median_interval = float(np.median(intervals))
        min_interval = float(np.min(intervals))
        max_interval = float(np.max(intervals))

        if median_interval > 0 and np.all(intervals > 0):
            max_interval_ratio = (
                max_interval / median_interval
            )
        else:
            max_interval_ratio = None
    else:
        mean_interval = None
        median_interval = None
        min_interval = None
        max_interval = None
        max_interval_ratio = None
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "rows": len(data),
        "columns": len(data.columns),
        "start_time": (
            float(time_values[0])
            if finite_time else None
        ),
        "end_time": (
            float(time_values[-1])
            if finite_time else None
        ),
        "monotonic": monotonic,
        "duplicates": duplicates,
        "missing": missing,
        "finite": finite,
        "mean_interval": mean_interval,
        "median_interval": median_interval,
        "min_interval": min_interval,
        "max_interval": max_interval,
        "max_interval_ratio": max_interval_ratio
    }
