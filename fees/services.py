from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import (
    Case,
    DecimalField,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from core.models import Term
from students.services import (
    enrollment_on,
    get_class_roster_for_term,
    has_enrollment_history,
)
from .models import FeeCharge, FeePayment, StudentCharge, StudentFeeAccount

_ZERO = Decimal('0.00')
_DECIMAL = DecimalField(max_digits=12, decimal_places=2)


def ensure_account(student, term):
    """Return the (unique) fee account for a student and term, creating it
    lazily inside the caller's transaction when it does not exist yet."""
    account, _ = StudentFeeAccount.objects.get_or_create(
        student=student, term=term
    )
    return account


def _charged_subquery():
    """Annotate a StudentFeeAccount queryset with total charged."""
    return Subquery(
        StudentCharge.objects.filter(
            student_id=OuterRef('student_id'), term_id=OuterRef('term_id'),
        ).order_by().values('student_id', 'term_id')
        .annotate(total=Sum('amount')).values('total')[:1],
        output_field=_DECIMAL,
    )


def _paid_subquery():
    """Annotate a StudentFeeAccount queryset with total non-voided paid."""
    return Subquery(
        FeePayment.objects.filter(
            account_id=OuterRef('pk'), voided=False,
        ).order_by().values('account_id')
        .annotate(total=Sum('amount')).values('total')[:1],
        output_field=_DECIMAL,
    )


def annotate_account_totals(queryset):
    """Attach total charged / total paid / net balance to an account queryset
    with no N+1 queries. Names avoid the model's read-only properties, so the
    annotation-injected attributes do not collide with them. Balance stays
    derived — never stored."""
    return queryset.annotate(
        charged=Coalesce(_charged_subquery(), _ZERO),
        paid=Coalesce(_paid_subquery(), _ZERO),
        owed=F('charged') - F('paid'),
    )


def _as_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _cs_id(class_stream):
    return getattr(class_stream, 'pk', class_stream)


def _class_at_date(student, day):
    """Class stream the student belonged to on ``day``: enrollment-backed,
    with the legacy Student.class_stream fallback when there is no enrollment
    history. Records are never modified by this lookup."""
    if has_enrollment_history(student):
        enrollment = enrollment_on(student, _as_date(day))
        if enrollment:
            return enrollment.class_stream_id
    return student.class_stream_id


def _attributed_charges_for_term(term):
    """Partition every StudentCharge for ``term`` among exactly one class per
    row, so no charge is ever counted twice across classes.

    Generated rows (fee_structure set) belong to their FeeCharge's class.
    Manual rows (fee_structure null) belong to the enrollment class on the
    charge date, falling back to the legacy Student.class_stream.

    Returns a (by_student, totals, class_rows) tuple:
      by_student : {student_id: {class_stream_id: amount}}
      totals     : {student_id: amount}  (the student's whole-term charges)
      class_rows : {class_stream_id: {charge_pk}}  (for recent-charge lists)
    """
    by_student = defaultdict(lambda: defaultdict(lambda: _ZERO))
    totals = defaultdict(lambda: _ZERO)
    class_rows = defaultdict(set)
    rows = StudentCharge.objects.filter(term=term).select_related(
        'student', 'fee_structure__class_stream',
    )
    for charge in rows:
        if charge.fee_structure_id:
            cs_id = charge.fee_structure.class_stream_id
        else:
            cs_id = _class_at_date(charge.student, charge.date)
        by_student[charge.student_id][cs_id] += charge.amount
        totals[charge.student_id] += charge.amount
        class_rows[cs_id].add(charge.pk)
    return by_student, totals, class_rows


def _paid_totals_by_student(term):
    """Non-voided paid per student for the term: {student_id: amount}."""
    rows = (
        FeePayment.objects.filter(account__term=term, voided=False)
        .order_by().values('account__student_id')
        .annotate(total=Sum('amount'))
    )
    return {
        row['account__student_id']: (row['total'] or _ZERO) for row in rows
    }


def _proportional_split(paid, weights):
    """Split ``paid`` across weighted parts so the parts sum to exactly
    ``paid`` to the cent (largest-remainder rounding). ``weights`` is an
    iterable of (key, Decimal weight)."""
    paid_cents = int((paid * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    total = sum(weight for _, weight in weights)
    if total <= 0 or paid_cents <= 0:
        return {key: _ZERO for key, _ in weights}
    parts = []
    for key, weight in weights:
        exact = weight * paid_cents / total
        flat = int(exact)
        parts.append([key, flat, exact - flat])
    remaining = paid_cents - sum(part[1] for part in parts)
    for part in sorted(parts, key=lambda part: part[2], reverse=True):
        if remaining == 0:
            break
        part[1] += 1
        remaining -= 1
    return {part[0]: Decimal(part[1]) / 100 for part in parts}


def _payments_attributed_to_class(term, student_id, class_stream_id):
    """Payments of a zero-charge student attributed to a class using the
    date/enrollment fallback. Presentation allocation only — payments and the
    account balance are never altered."""
    payments = FeePayment.objects.filter(
        account__term=term, account__student_id=student_id, voided=False,
    ).select_related('account__student')
    total = _ZERO
    for payment in payments:
        if _class_at_date(payment.account.student, payment.date) == class_stream_id:
            total += payment.amount
    return total


def _term_class_finance(term, class_stream):
    """Class-attributed finance for one term and one class stream.

    Returns (charged, paid, owed, class_rows) dicts keyed by student_id,
    covering every student with a financial footprint in the class for the
    term. Every student's charges are partitioned among their classes and
    payments are allocated proportionally, so per-class balances reconcile
    exactly with the account balance. Nothing is persisted.
    """
    cs_id = _cs_id(class_stream)
    by_student, totals, class_rows = _attributed_charges_for_term(term)
    paid_totals = _paid_totals_by_student(term)

    class_charged = {
        student_id: classes.get(cs_id, _ZERO)
        for student_id, classes in by_student.items()
        if cs_id in classes
    }

    class_paid = {}
    for student_id, paid in paid_totals.items():
        if paid <= 0:
            continue
        total = totals.get(student_id, _ZERO)
        if total > 0:
            allocated = _proportional_split(paid, by_student[student_id].items()).get(
                cs_id, _ZERO
            )
            if allocated > 0:
                class_paid[student_id] = allocated
        else:
            allocated = _payments_attributed_to_class(term, student_id, cs_id)
            if allocated > 0:
                class_paid[student_id] = allocated

    report = set(class_charged) | set(class_paid)
    charged = {student_id: class_charged.get(student_id, _ZERO) for student_id in report}
    paid = {student_id: class_paid.get(student_id, _ZERO) for student_id in report}
    owed = {student_id: charged[student_id] - paid[student_id] for student_id in report}
    return charged, paid, owed, class_rows


def _accounts_class_slices(queryset, term, class_stream_id):
    """Map {account_pk: (charged, paid, owed)} for one class stream.

    ``term`` may be None, in which case every term represented by the
    queryset is attributed separately. Accounts with no footprint in the
    class are omitted."""
    slices = {}
    if term is None:
        for term_id in queryset.values_list('term_id', flat=True).distinct():
            accounts_in_term = queryset.filter(term_id=term_id)
            charged, paid, owned, _ = _term_class_finance(
                Term.objects.get(pk=term_id), class_stream_id
            )
            for pk, student_id in accounts_in_term.values_list('pk', 'student_id'):
                charge = charged.get(student_id, _ZERO)
                payment = paid.get(student_id, _ZERO)
                if charge != 0 or payment != 0:
                    slices[pk] = (charge, payment, charge - payment)
        return slices

    accounts_in_term = queryset.filter(term=term)
    charged, paid, _owed, _ = _term_class_finance(term, class_stream_id)
    for pk, student_id in accounts_in_term.values_list('pk', 'student_id'):
        charge = charged.get(student_id, _ZERO)
        payment = paid.get(student_id, _ZERO)
        if charge != 0 or payment != 0:
            slices[pk] = (charge, payment, charge - payment)
    return slices


def _annotate_class_slices(queryset, slices):
    """Annotate an account queryset with class-attributed charged/paid/owed,
    dropping accounts outside the class footprint."""
    def _case(mapping):
        if not mapping:
            return Value(_ZERO, output_field=_DECIMAL)
        return Case(
            *[
                When(Q(pk=pk), then=Value(value, output_field=_DECIMAL))
                for pk, value in mapping.items()
            ],
            default=Value(_ZERO, output_field=_DECIMAL),
            output_field=_DECIMAL,
        )

    charged = _case({pk: value[0] for pk, value in slices.items()})
    paid = _case({pk: value[1] for pk, value in slices.items()})
    owed = _case({pk: value[2] for pk, value in slices.items()})
    return queryset.filter(pk__in=list(slices.keys())).annotate(
        charged=charged, paid=paid, owed=owed,
    )


def annotate_class_totals(queryset, class_stream, term=None):
    """Class-attributed charged/paid/owed for a StudentFeeAccount queryset.

    Used by class-filtered account lists and outstanding-account reports so an
    account is never shown with its whole balance under two classes."""
    return _annotate_class_slices(
        queryset, _accounts_class_slices(queryset, term, _cs_id(class_stream))
    )


def generate_charges_for_class(class_stream, term, user):
    """Idempotently generate StudentCharge records for every active student in
    a class stream from the class's active FeeCharge structures.

    Returns the number of charge rows created or updated. Re-running the same
    generation converges on the same rows thanks to the unique
    (student, term, fee_structure) constraint.
    """
    structures = FeeCharge.objects.filter(
        class_stream=class_stream, term=term, is_active=True,
    )
    students = get_class_roster_for_term(class_stream, term).order_by('admission_no')
    with transaction.atomic():
        touched = 0
        for structure in structures:
            for student in students:
                ensure_account(student, term)
                StudentCharge.objects.update_or_create(
                    student=student,
                    term=term,
                    fee_structure=structure,
                    defaults={
                        'description': structure.description,
                        'amount': structure.amount,
                        'created_by': user,
                    },
                )
                touched += 1
        return touched


class _StatementAccount:
    """Read-only stand-in for a StudentFeeAccount when none exists yet."""

    pk = None

    def __init__(self, student, term):
        self.student = student
        self.term = term


def charge_statement(account):
    """Rows for a student fee statement plus running balance.

    Each row: date, description, kind ('charge'/'payment'), amount, balance.
    Charges and payments are merged in date order (charges before payments on
    the same date), and the running balance is derived from the actual records.
    """
    charge_qs = StudentCharge.objects.filter(
        student=account.student, term=account.term,
    ).order_by('date', 'id')
    if account.pk:
        payment_qs = FeePayment.objects.filter(
            account=account, voided=False,
        ).order_by('date', 'id')
        payments = list(payment_qs)
    else:
        payments = []

    rows = []
    for charge in charge_qs:
        rows.append({
            'date': charge.date,
            'kind': 'charge',
            'description': charge.description,
            'amount': charge.amount,
            'notes': charge.notes,
        })
    for payment in payments:
        rows.append({
            'date': payment.date,
            'kind': 'payment',
            'description': f'{payment.get_method_display()} payment',
            'amount': payment.amount,
            'notes': payment.notes,
        })

    rows.sort(key=lambda row: (row['date'], 0 if row['kind'] == 'charge' else 1))
    running = _ZERO
    for row in rows:
        if row['kind'] == 'charge':
            running += row['amount']
        else:
            running -= row['amount']
        row['balance'] = running
    return rows


def statement_for(student, term):
    """Statement rows without writing an account row (used on read-only pages)."""
    return charge_statement(_StatementAccount(student, term))


def parent_children_finance(parent):
    """Children of a parent with aggregated totals from the student's finance
    records. Deactivated children remain visible so financial history is not
    hidden."""
    students = parent.children.select_related(
        'class_stream__school_class', 'class_stream__stream'
    ).order_by('admission_no')
    charged = Subquery(
        StudentCharge.objects.filter(
            student_id=OuterRef('pk'),
        ).order_by().values('student_id')
        .annotate(total=Sum('amount')).values('total')[:1],
        output_field=_DECIMAL,
    )
    paid = Subquery(
        FeePayment.objects.filter(
            account__student_id=OuterRef('pk'), voided=False,
        ).order_by().values('account__student_id')
        .annotate(total=Sum('amount')).values('total')[:1],
        output_field=_DECIMAL,
    )
    return students.annotate(
        total_charged=Coalesce(charged, _ZERO),
        total_paid=Coalesce(paid, _ZERO),
        balance=F('total_charged') - F('total_paid'),
    )


def student_term_balance(student, term):
    charged = StudentCharge.objects.filter(
        student=student, term=term,
    ).aggregate(total=Sum('amount'))['total'] or _ZERO
    paid = FeePayment.objects.filter(
        account__student=student, account__term=term, voided=False,
    ).aggregate(total=Sum('amount'))['total'] or _ZERO
    return charged - paid


def finance_dashboard_stats(term, class_stream=None):
    """Aggregated finance statistics for one term (optionally one class).

    With a class stream, charges are attributed to the class by their own
    class context and non-voided payments are allocated proportionally, so a
    mid-term promotee's term balance is never counted in full under two
    classes. Every number is fully derived — nothing here is stored.
    """
    if class_stream is None:
        charge_qs = StudentCharge.objects.filter(term=term)
        payment_qs = FeePayment.objects.filter(account__term=term, voided=False)

        total_charged = charge_qs.aggregate(total=Sum('amount'))['total'] or _ZERO
        total_paid = payment_qs.aggregate(total=Sum('amount'))['total'] or _ZERO

        accounts = annotate_account_totals(
            StudentFeeAccount.objects.filter(term=term)
        )
        balances = list(accounts.values('owed'))

        outstanding = sum(
            (row['owed'] or _ZERO) for row in balances if (row['owed'] or _ZERO) > 0
        )
        owing_count = sum(1 for row in balances if (row['owed'] or _ZERO) > 0)
        paid_full_count = sum(1 for row in balances if (row['owed'] or _ZERO) <= 0)
        in_credit_count = sum(1 for row in balances if (row['owed'] or _ZERO) < 0)

        recent_charges = charge_qs.select_related(
            'student', 'student__class_stream__school_class',
        ).order_by('-date', '-id')[:8]
        recent_payments = payment_qs.select_related(
            'account__student', 'account__student__class_stream__school_class',
            'recorded_by',
        ).order_by('-date', '-id')[:8]

        return {
            'total_charged': total_charged,
            'total_paid': total_paid,
            'outstanding': outstanding,
            'owing_count': owing_count,
            'paid_full_count': paid_full_count,
            'in_credit_count': in_credit_count,
            'recent_charges': recent_charges,
            'recent_payments': recent_payments,
        }

    cs_id = _cs_id(class_stream)
    charged, paid, owed, class_rows = _term_class_finance(term, class_stream)

    total_charged = sum(charged.values())
    total_paid = sum(paid.values())
    outstanding = sum(value for value in owed.values() if value > 0)
    owing_count = sum(1 for value in owed.values() if value > 0)
    paid_full_count = sum(1 for value in owed.values() if value <= 0)
    in_credit_count = sum(1 for value in owed.values() if value < 0)

    recent_charges = StudentCharge.objects.filter(
        pk__in=class_rows.get(cs_id, set()),
    ).select_related(
        'student', 'student__class_stream__school_class',
    ).order_by('-date', '-id')[:8]
    recent_payments = FeePayment.objects.filter(
        account__term=term, voided=False, account__student_id__in=list(owed),
    ).select_related(
        'account__student', 'account__student__class_stream__school_class',
        'recorded_by',
    ).order_by('-date', '-id')[:8]

    return {
        'total_charged': total_charged,
        'total_paid': total_paid,
        'outstanding': outstanding,
        'owing_count': owing_count,
        'paid_full_count': paid_full_count,
        'in_credit_count': in_credit_count,
        'recent_charges': recent_charges,
        'recent_payments': recent_payments,
    }


def outstanding_accounts(term=None, class_stream=None):
    """Accounts that are not settled (owing or in credit), most owed first.

    Without a class stream this is the plain per-account list. With a class
    stream the balances are class-attributed, so an account never carries its
    whole balance under two classes."""
    queryset = StudentFeeAccount.objects.select_related(
        'student', 'term', 'student__class_stream__school_class',
        'student__class_stream__stream',
    )
    if term:
        queryset = queryset.filter(term=term)
    if class_stream is None:
        return annotate_account_totals(queryset).exclude(
            owed=0
        ).order_by('-owed')
    return annotate_class_totals(queryset, class_stream, term).exclude(
        owed=0
    ).order_by('-owed')