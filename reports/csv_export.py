import csv

from django.http import HttpResponse


def csv_response(filename, headers, rows):
    """A download attachment response. ``headers`` is a list of column names
    and ``rows`` an iterable of equally-wide lists."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


def _percent(value):
    return f'{value:.2f}' if value is not None else ''


def class_performance_csv(report):
    headers = [
        'Term', 'Class', 'Adm No', 'Student Name', 'Status',
        'Position', 'Overall %', 'Grade',
        'Assessments Recorded', 'Assessments Used', 'Subjects Recorded',
        'Subjects Used',
    ]
    term = report['term']
    class_stream = report['class_stream']
    rows = []
    for entry in report['rows']:
        rows.append([
            f'{term}',
            f'{class_stream}',
            entry['student'].admission_no,
            entry['student'].full_name,
            entry['student'].get_status_display(),
            entry['position'] if entry['position'] is not None else '',
            _percent(entry['overall_percent']),
            entry['overall_grade'].label if entry['overall_grade'] else '',
            entry['records'],
            entry['total'],
            entry['subjects'],
            entry['subjects_required'],
        ])
    return headers, rows


def student_report_csv(data):
    """Report-card rows: one row per subject, an overall row, then one row
    per ranked class."""
    headers = [
        'Adm No', 'Student Name', 'Term', 'Section', 'Detail',
        'Total', 'Max', 'Average %', 'Grade', 'Position', 'Ranked Count',
    ]
    student = data['student']
    term = data['term']
    results = data['results']
    preface = [
        student.admission_no, student.full_name, f'{term}',
    ]
    rows = []
    for row in results['rows']:
        rows.append([
            *preface,
            'Subject', row['subject'].name,
            row['total'], row['max'],
            _percent(row['avg_percent']),
            row['grade'].label if row['grade'] else '',
            '', '',
        ])
    rows.append([
        *preface,
        'Subject', 'OVERALL',
        results['totals']['scored'], results['totals']['max'],
        _percent(results['overall_percent']),
        results['overall_grade'].label if results['overall_grade'] else '',
        '', '',
    ])
    for rank in data['ranks']:
        rows.append([
            *preface,
            'Class', f'{rank["class_stream"]}',
            '', '', _percent(rank['overall_percent']),
            rank['overall_grade'].label if rank['overall_grade'] else '',
            rank['position'] if rank['position'] is not None else '',
            rank['ranked_count'],
        ])
    return headers, rows


def attendance_csv(report):
    headers = [
        'Term', 'Class', 'Adm No', 'Student Name', 'Status',
        'Present', 'Late', 'Absent', 'Excused', 'Recorded Days',
        'Attendance %',
    ]
    term = report['term']
    class_stream = report['class_stream']
    rows = []
    for entry in report['rows']:
        rows.append([
            f'{term}',
            f'{class_stream}',
            entry['student'].admission_no,
            entry['student'].full_name,
            entry['student'].get_status_display(),
            entry['present'],
            entry['late'],
            entry['absent'],
            entry['excused'],
            entry['recorded_days'],
            _percent(entry['percent']),
        ])
    return headers, rows


def finance_csv(report):
    headers = [
        'Term', 'Class', 'Adm No', 'Student Name',
        'Charged (KSh)', 'Paid (KSh)', 'Owed (KSh)',
    ]
    term = report['term']
    class_stream = report['class_stream']
    rows = []
    for entry in report['rows']:
        rows.append([
            f'{term}',
            f'{class_stream}',
            entry['student'].admission_no,
            entry['student'].full_name,
            f'{entry["charged"]:.2f}',
            f'{entry["paid"]:.2f}',
            f'{entry["owed"]:.2f}',
        ])
    return headers, rows