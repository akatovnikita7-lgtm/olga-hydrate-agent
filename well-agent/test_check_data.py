import pandas as pd
import numpy as np
from src.results.reader import check_data

def test_valid_data():
    """Проверка корректных данных."""

    data = pd.DataFrame({
        "time_s": [0, 10, 20],
        "PT": [1.0, 1.1, 1.2]
    })

    result = check_data(data)

    assert result["valid"] is True
    assert result["errors"] == []
    assert result["monotonic"] is True

def test_duplicate_time():
    """Проверка повторяющихся временных отметок."""
    data = pd.DataFrame({
        "time_s": [0, 10, 10],
        "PT": [1.0, 1.1, 1.2]
    })
    result = check_data(data)
    assert result["valid"] is False
    assert result["duplicates"] == 1
    assert result["monotonic"] is False


def test_time_not_increasing():
    """Проверка нарушения порядка времени."""
    data = pd.DataFrame({
        "time_s": [0, 10, 5],
        "PT": [1.0, 1.1, 1.2]
    })

    result = check_data(data)
    assert result["valid"] is False
    assert result["duplicates"] == 0
    assert result["monotonic"] is False


def test_missing_values():
    """Проверка пропущенных значений."""
    data = pd.DataFrame({
        "time_s": [0, 10, 20],
        "PT": [1.0, np.nan, 1.2]
    })
    result = check_data(data)
    assert result["valid"] is False
    assert result["missing"] == 1
    assert result["finite"] is False


def test_infinite_values():
    """Проверка бесконечных значений."""
    data = pd.DataFrame({
        "time_s": [0, 10, 20],
        "PT": [1.0, np.inf, 1.2]
    })
    result = check_data(data)
    assert result["valid"] is False
    assert result["missing"] == 0
    assert result["finite"] is False


def test_empty_data():
    """Проверка пустой таблицы."""
    data = pd.DataFrame()
    result = check_data(data)
    assert result["valid"] is False
    assert "Таблица пустая" in result["errors"]
    assert result["rows"] == 0


def test_missing_time_column():
    """Проверка отсутствующего столбца времени."""
    data = pd.DataFrame({
        "PT": [1.0, 1.1, 1.2]
    })
    result = check_data(data)
    assert result["valid"] is False
    assert "Отсутствует столбец time_s" in result["errors"]


def test_single_data_point():
    """Проверка недостаточного количества точек."""
    data = pd.DataFrame({
        "time_s": [0],
        "PT": [1.0]
    })
    result = check_data(data)
    assert result["valid"] is False
    assert result["monotonic"] is False
    assert "Недостаточно точек для анализа" in result["errors"]

def test_non_numeric_values():
    """Проверка текстовых значений в числовых каналах."""
    data = pd.DataFrame({
        "time_s": [0, 10, 20],
        "PT": [1.0, "abc", 1.2]
    })
    result = check_data(data)
    assert result["valid"] is False
    assert any(
        "Нечисловых значений" in error
        for error in result["errors"]
    )


def test_negative_time():
    """Проверка отрицательного времени моделирования."""
    data = pd.DataFrame({
        "time_s": [-10, 0, 10],
        "PT": [1.0, 1.1, 1.2]
    })
    result = check_data(data)
    assert result["valid"] is False
    assert any(
        "Отрицательное время" in error
        for error in result["errors"]
    )



def test_irregular_time_steps():
    """Проверка неравномерного временного шага."""

    data = pd.DataFrame({
        "time_s": [0, 10, 20, 50],
        "PT": [1.0, 1.1, 1.2, 1.3]
    })
    result = check_data(data)
    assert result["valid"] is True
    assert result["monotonic"] is True
    assert result["min_interval"] == 10.0
    assert result["median_interval"] == 10.0
    assert result["max_interval"] == 30.0
    assert np.isclose(
        result["mean_interval"],
        50 / 3
    )
    assert result["max_interval_ratio"] == 3.0
