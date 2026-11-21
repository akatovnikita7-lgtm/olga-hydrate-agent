"""Compare automatic OLGA trends with the team's manual reference."""
import json
from pathlib import Path

import pandas as pd

from .analysis import summarize_interval_volumes, summarize_periods, summarize_transition

REFERENCE = Path(__file__).resolve().parents[2] / 'results/manual_case1_obhod/metrics.json'
PERIODS = {'До переключения': (47, 48), 'Переходный процесс': (48, 50),
           'После переключения': (90, 96)}
VOLUME_PERIODS = {'До переключения': (47, 48), 'Переходный процесс': (48, 52.5),
                  'После стабилизации': (52.5, 56)}


def compare_reference(data, catalog, pairs, schedule, output):
    """Return a CSV path or an explanation of why comparison was skipped."""
    if not REFERENCE.is_file():
        return None, 'Отсутствует отчёт ручного прогона.'
    baseline = json.loads(REFERENCE.read_text(encoding='utf-8'))
    event = baseline['event']
    if (schedule['event_time_s'], schedule['transition_s'], schedule['end_time_s']) != (
            event['event_time_s'], event['transition_duration_s'], 345600):
        return None, 'Расписание отличается от ручного прогона.'
    branches = list(dict.fromkeys(row['branch'] for row in baseline['period_summary']))
    matched_branches = []
    for branch in branches:
        channels = catalog[catalog.branch == branch]
        units = {
            variable: channels.loc[channels.variable == variable, 'unit'].str.strip('() ').str.upper().tolist()
            for variable in ('PT', 'QLT')
        }
        if units == {'PT': ['PA'], 'QLT': ['M3/S']}:
            matched_branches.append(branch)
    if not matched_branches:
        return None, 'Нет сопоставимых каналов давления и расхода.'
    data = data.assign(time_h=data.time_s / 3600)
    if any(not data.time_h.between(start, end, inclusive='left').any() for start, end in PERIODS.values()):
        return None, 'В одном из периодов сравнения нет сохранённых точек.'
    groups = [
        ('period_summary', ('branch', 'period'), summarize_periods(data, catalog, matched_branches, PERIODS)),
        ('transition_summary', ('branch',), summarize_transition(data, catalog, matched_branches)),
    ]
    if pairs and data.time_s.iloc[0] <= 47 * 3600 and data.time_s.iloc[-1] >= 56 * 3600:
        groups.append(('interval_volumes', ('branch', 'period', 'start_h', 'end_h'),
                       summarize_interval_volumes(data, catalog.loc[pairs], VOLUME_PERIODS)))
    rows = []
    for group, keys, frame in groups:
        automatic = {
            tuple(record[k] for k in keys): record
            for record in json.loads(frame.to_json(orient='records', double_precision=15))
        }
        for row in baseline[group]:
            candidate = automatic.get(tuple(row[k] for k in keys), {})
            for metric, manual in row.items():
                if metric in keys or metric == 'points' or not isinstance(manual, (int, float)):
                    continue
                calculated = candidate.get(metric)
                difference = None if calculated is None else abs(calculated - manual)
                rows.append({
                    'group': group, 'branch': row['branch'], 'period': row.get('period'),
                    'metric': metric, 'manual_value': manual, 'automatic_value': calculated,
                    'absolute_error': difference,
                    'relative_error_pct': None if difference is None or manual == 0 else 100 * difference / abs(manual),
                    'assessment': 'NOT_ASSESSED',
                    'reason': 'Нет сопоставимого значения' if difference is None else 'Инженерный допуск не задан',
                })
    path = output / 'comparison.csv'
    pd.DataFrame(rows).to_csv(path, encoding='utf-8-sig', index=False)
    return path, None
