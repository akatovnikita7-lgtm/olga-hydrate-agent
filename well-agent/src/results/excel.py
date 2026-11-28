"""Export saved OLGA CSVs into a workbook with one sheet per table."""
import csv
import math
from pathlib import Path
from tempfile import TemporaryDirectory

TABLES = [
    ('comparison.csv', 'Сравнение'),
    ('volumes.csv', 'Объёмы'),
    ('channels.csv', 'Каналы'),
    ('series.csv', 'Временные ряды'),
]
TEXT_COLUMNS = {
    'group', 'branch', 'period', 'metric', 'assessment', 'reason',
    'column', 'variable', 'location_type', 'pipe', 'nr', 'unit', 'description',
}


def export_excel(directory: Path) -> Path:
    import xlsxwriter

    inputs = [(directory / filename, label) for filename, label in TABLES
              if (directory / filename).is_file()]
    if not inputs:
        raise FileNotFoundError(f'No OLGA CSV tables in {directory}')
    output = directory / 'results.xlsx'
    with TemporaryDirectory(dir=directory) as temporary:
        workbook_path = Path(temporary) / output.name
        options = {'constant_memory': True, 'tmpdir': temporary,
                   'strings_to_formulas': False, 'strings_to_urls': False}
        with xlsxwriter.Workbook(workbook_path, options) as workbook:
            heading = workbook.add_format({'bold': True, 'bg_color': '#DCEAF7'})
            for path, label in inputs:
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    rows = csv.reader(stream)
                    headers = next(rows)
                    sheet = workbook.add_worksheet(label)
                    sheet.write_row(0, 0, headers, heading)
                    widths = [max(14, min(44, len(header) + 3)) for header in headers]
                    last_row = 0
                    for last_row, row in enumerate(rows, start=1):
                        if last_row >= 1048576 or len(headers) > 16384:
                            raise ValueError(f'{path.name} exceeds Excel worksheet limits')
                        for column, (header, value) in enumerate(zip(headers, row, strict=True)):
                            if not value:
                                continue
                            if header not in TEXT_COLUMNS:
                                try:
                                    number = float(value)
                                except ValueError:
                                    pass
                                else:
                                    if math.isfinite(number):
                                        sheet.write_number(last_row, column, number)
                                        continue
                            sheet.write_string(last_row, column, value)
                            widths[column] = max(widths[column], min(50, len(value) + 3))
                    for index, width in enumerate(widths):
                        sheet.set_column(index, index, width)
                    sheet.freeze_panes(1, 1)
                    sheet.autofilter(0, 0, last_row, len(headers) - 1)
        workbook_path.replace(output)
    return output
