"""Adapter entry point: numerical exports and plots from this run's TPL."""
from pathlib import Path
import json
import numpy as np
from .reader import load_run, check_data
from .analysis import summarize_interval_volumes
from .comparison import compare_reference
from .excel import export_excel


def analyze_run(model_dir: Path, manifest: dict, run_info: dict) -> dict:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    model_dir = Path(model_dir)
    source = model_dir / manifest['expected_outputs']['trend']
    data, catalog = load_run(source)
    quality = check_data(data)
    if not quality['valid']:
        raise ValueError('Invalid or insufficient time series')
    schedule = manifest['schedule']
    event = float(schedule['event_time_s'])
    transition_end = event + float(schedule['transition_s'])
    end = float(schedule['end_time_s'])
    if data.time_s.iloc[0] > 0 or data.time_s.iloc[-1] < end - 20:
        raise ValueError('Incomplete simulation period')
    out = model_dir / 'analysis'
    out.mkdir(exist_ok=True)
    artifacts = []
    def artifact(path, kind):
        artifacts.append({'kind': kind, 'path': str(path.resolve())})
    data.to_csv(out / 'series.csv', index=False)
    catalog.to_csv(out / 'channels.csv', index=False)
    artifact(out / 'series.csv', 'numeric_export')
    artifact(out / 'channels.csv', 'channel_map')
    transition_rows = int(data.time_s.between(event, transition_end).sum())
    warnings = []
    if transition_rows < 3:
        warnings.append('Переход сохранён менее чем в трёх точках; его форму оценить нельзя.')
    metrics, selected = [], []
    for point in manifest['checkpoints']:
        matches = catalog[(catalog.variable == point['variable']) & (catalog.branch == point['branch'])]
        if len(matches) != 1:
            warnings.append(f"{point['location_id']}: найдено каналов {len(matches)}, нужен точный SECTION/BOUNDARY, PIPE, NR.")
            continue
        channel = matches.iloc[0]
        unit = str(channel.unit).strip('() ').upper()
        if unit != point['unit'].upper():
            warnings.append(f"{point['location_id']}: неожиданная единица {unit}.")
            continue
        selected.append((point, channel))
        values = data[channel.column]
        for name, value in [('initial', values.iloc[0]), ('final', values.iloc[-1]), ('min', values.min()), ('max', values.max())]:
            metrics.append({'name': name, 'location_id': channel.column, 'value': float(value),
                'unit': unit, 'source': str(source.resolve())})
    with source.open(encoding='utf-8', errors='replace') as stream:
        synthetic = 'FAKE' in stream.readline().upper()
    for filename, bounds in [('overview.png', None), ('transition.png', (event/3600-1, event/3600+2))]:
        fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
        fig.suptitle('SYNTHETIC TEST — NOT OLGA RESULTS' if synthetic else 'OLGA results')
        for point, channel in selected:
            index = 0 if point['variable'] == 'GT' else 1
            scale = 1 if index == 0 else 1e-5
            axes[index].plot(data.time_s / 3600, data[channel.column] * scale, label=f'{channel.branch} / {channel.location_type} {channel.nr}')
        for ax, label in zip(axes, ['Mass flow [kg/s]', 'Pressure [bar]']):
            ax.set_ylabel(label)
            ax.axvline(event/3600, color='black', linestyle='--')
            ax.axvline(transition_end/3600, color='grey', linestyle=':')
            ax.grid(True, alpha=.3)
            if ax.lines and ax.get_legend_handles_labels()[1]:
                ax.legend(fontsize=7)
            if bounds:
                ax.set_xlim(*bounds)
        axes[-1].set_xlabel('Model time [h]')
        fig.tight_layout()
        fig.savefig(out / filename, dpi=150)
        plt.close(fig)
        artifact(out / filename, 'plot')
    # Reuse the colleagues' volume analysis only for exact channel pairs and known units.
    pair_keys = ['branch', 'location_type', 'pipe', 'nr']
    pairs = []
    for _, group in catalog[catalog.variable.isin(['QLT', 'ACCLIQ'])].groupby(pair_keys):
        if set(group.variable) == {'QLT', 'ACCLIQ'} and len(group) == 2:
            units = {r.variable: r.unit.strip('() ').upper() for _, r in group.iterrows()}
            if units == {'QLT': 'M3/S', 'ACCLIQ': 'M3'}:
                pairs.extend(group.index)
    if pairs:
        volumes = summarize_interval_volumes(data, catalog.loc[pairs],
            {'before': (0, event/3600), 'transition': (event/3600, transition_end/3600),
             'after': (transition_end/3600, end/3600)})
        volumes.to_csv(out / 'volumes.csv', index=False)
        artifact(out / 'volumes.csv', 'volume_table')
    if not synthetic:
        comparison, issue = compare_reference(data, catalog, pairs, schedule, out)
        if comparison:
            artifact(comparison, 'manual_comparison')
        elif issue:
            warnings.append(issue)
    try:
        workbook = export_excel(out)
    except (ImportError, OSError, ValueError) as error:
        warnings.append(f'Excel-выгрузка недоступна: {error}. Исходные CSV сохранены.')
    else:
        artifact(workbook, 'excel_workbook')
    result = {'metrics': metrics, 'series': [], 'artifacts': artifacts,
        'assessment': {'status': 'NOT_ASSESSED',
            'reason': 'Расчёт прочитан; допустимые давления и инженерные критерии не заданы.',
            'warnings': warnings, 'transition_points': transition_rows},
        'run': run_info}
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    artifact(out / 'summary.json', 'summary')
    return result
