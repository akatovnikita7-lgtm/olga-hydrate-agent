import numpy as np
import pandas as pd
import pytest
from src.results.analysis import summarize_interval_volumes

def make_case(time, flow, accumulated):
    """Создание тестовых данных и каталога каналов."""
    data = pd.DataFrame({
        "time_s": time,
        "acc_col": accumulated,
        "qlt_col": flow
    })
    catalog = pd.DataFrame([
        {
            "branch": "BRANCH_1",
            "location_type": "BOUNDARY",
            "pipe": "PIPE-1",
            "nr": 2,
            "variable": "ACCLIQ",
            "column": "acc_col"
        },
        {
            "branch": "BRANCH_1",
            "location_type": "BOUNDARY",
            "pipe": "PIPE-1",
            "nr": 2,
            "variable": "QLT",
            "column": "qlt_col"
        }
    ])
    return data, catalog

def test_constant_flow():
    """Постоянный расход."""
    data, catalog = make_case(
        [0, 3600, 7200],
        [2, 2, 2],
        [0, 7200, 14400]
    )
    result = summarize_interval_volumes(
        data, catalog, {"test": (0, 2)}
    ).iloc[0]
    assert np.isclose(result["integral_QLT_m3"], 14400)
    assert np.isclose(result["delta_ACCLIQ_m3"], 14400)
    assert np.isclose(result["mean_flow_m3_h"], 7200)

def test_linear_flow():
    """Линейно изменяющийся расход."""
    data, catalog = make_case(
        [0, 3600, 7200],
        [0, 1, 2],
        [0, 1800, 7200]
    )
    result = summarize_interval_volumes(
        data, catalog, {"test": (0, 2)}
    ).iloc[0]
    assert np.isclose(result["integral_QLT_m3"], 7200)
    assert np.isclose(result["delta_ACCLIQ_m3"], 7200)

def test_nonuniform_time_grid():
    """Неравномерный временной шаг."""
    data, catalog = make_case(
        [0, 1800, 7200],
        [2, 2, 2],
        [0, 3600, 14400]
    )
    result = summarize_interval_volumes(
        data, catalog, {"test": (0, 2)}
    ).iloc[0]
    assert np.isclose(result["integral_QLT_m3"], 14400)

def test_interpolation_at_boundaries():
    """Интерполяция на границах периода."""

    data, catalog = make_case(
        [0, 3600, 7200],
        [2, 2, 2],
        [0, 7200, 14400]
    )
    result = summarize_interval_volumes(
        data, catalog, {"test": (0.5, 1.5)}
    ).iloc[0]
    assert np.isclose(result["integral_QLT_m3"], 7200)
    assert np.isclose(result["delta_ACCLIQ_m3"], 7200)


def test_negative_flow():
    """Отрицательный расход и направление потока."""
    data, catalog = make_case(
        [0, 3600, 7200],
        [-1, -1, -1],
        [0, -3600, -7200]
    )
    result = summarize_interval_volumes(
        data, catalog, {"test": (0, 2)}
    ).iloc[0]
    assert np.isclose(result["integral_QLT_m3"], -7200)
    assert np.isclose(result["mean_flow_m3_h"], -3600)


def test_zero_flow():
    """Нулевой расход."""

    data, catalog = make_case(
        [0, 3600, 7200],
        [0, 0, 0],
        [0, 0, 0]
    )
    result = summarize_interval_volumes(
        data, catalog, {"test": (0, 2)}
    ).iloc[0]
    assert np.isclose(result["integral_QLT_m3"], 0)
    assert np.isclose(result["delta_ACCLIQ_m3"], 0)
    assert np.isnan(result["relative_error_pct"])


@pytest.mark.parametrize(
    "period",
    [
        (1, 1),
        (2, 1),
        (-1, 1),
        (1, 3)
    ]
)
def test_invalid_period(period):
    """Некорректные границы временного периода."""
    data, catalog = make_case(
        [0, 3600, 7200],
        [1, 1, 1],
        [0, 3600, 7200]
    )
    with pytest.raises(ValueError):
        summarize_interval_volumes(
            data, catalog, {"test": period}
        )


def test_missing_qlt_channel():
    """Отсутствующий канал QLT."""
    data, catalog = make_case(
        [0, 3600, 7200],
        [1, 1, 1],
        [0, 3600, 7200]
    )
    catalog = catalog[catalog["variable"] != "QLT"]
    with pytest.raises(ValueError, match="Некорректная пара"):
        summarize_interval_volumes(
            data, catalog, {"test": (0, 2)}
        )


def test_duplicate_qlt_channel():
    """Дублирующийся канал QLT."""
    data, catalog = make_case(
        [0, 3600, 7200],
        [1, 1, 1],
        [0, 3600, 7200]
    )
    duplicate = catalog[catalog["variable"] == "QLT"]
    catalog = pd.concat([catalog, duplicate], ignore_index=True)
    with pytest.raises(ValueError, match="Некорректная пара"):
        summarize_interval_volumes(
            data, catalog, {"test": (0, 2)}
        )


def test_nonfinite_qlt():
    """Бесконечные или пропущенные значения расхода."""
    data, catalog = make_case(
        [0, 3600, 7200],
        [1, np.nan, 1],
        [0, 3600, 7200]
    )
    with pytest.raises(ValueError, match="Ошибка данных QLT"):
        summarize_interval_volumes(
            data, catalog, {"test": (0, 2)}
        )


def test_non_increasing_time():
    """Нарушение порядка временных отметок."""
    data, catalog = make_case(
        [0, 3600, 3600],
        [1, 1, 1],
        [0, 3600, 3600]
    )
    with pytest.raises(ValueError, match="Время должно строго возрастать"):
        summarize_interval_volumes(
            data, catalog, {"test": (0, 2)}
        )
