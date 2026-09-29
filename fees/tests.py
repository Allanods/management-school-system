from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import localdate

from core.models import (
    AcademicYear,
    ClassStream,
    Department,
    SchoolClass,
    Stream,
    Teacher,
    Term,
)
from fees.models import FeeCharge, FeePayment, StudentCharge, StudentFeeAccount
from fees.services import (
    annotate_account_totals,
    charge_statement,
    finance_dashboard_stats,
    generate_charges_for_class,
    outstanding_accounts,
    parent_children_finance,
)
from students.models import Parent, Student, StudentParent
from students.services import promote_student, record_admission


class FeeBase(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            name='2026', start_date='2026-01-01', end_date='2026-12-31',
            is_current=True,
        )
        self.term = Term.objects.create(
            name='Term 1', year=self.year, start_date='2026-01-10',
            end_date='2026-04-10', is_current=True,
        )
        self.term2 = Term.objects.create(
            name='Term 2', year=self.year, start_date='2026-04-20',
            end_date='2026-07-20',
        )
        self.klass_2 = SchoolClass.objects.create(name='Form 2')
        self.klass_3 = SchoolClass.objects.create(name='Form 3')
        self.stream_a = Stream.objects.create(name='A')
        self.cs_2a = ClassStream.objects.create(
            school_class=self.klass_2, stream=self.stream_a
        )
        self.cs_3a = ClassStream.objects.create(
            school_class=self.klass_3, stream=self.stream_a
        )
        self.dept = Department.objects.create(name='Science', code='SCI')

        self.admin = self._make_user('admin', 'ADMIN')
        self.teacher_user = self._make_user('teacher1', 'TEACHER')
        self.teacher = Teacher.objects.create(
            user=self.teacher_user, employee_no='T001', first_name='John',
            last_name='Kamau', gender='M', date_joined='2024-01-10',
            department=self.dept,
        )
        self.parent_user = self._make_user('parent1', 'PARENT')
        self.parent = Parent.objects.create(
            user=self.parent_user, first_name='Mary', last_name='Wanjiru',
            phone='0700000000',
        )

        self.s1 = self._make_student(
            '2026/001', 'John', 'Kamau', self.cs_2a, Student.Status.ACTIVE
        )
        self.s2 = self._make_student(
            '2026/002', 'Mary', 'Wanjiku', self.cs_2a, Student.Status.ACTIVE
        )
        self.s3 = self._make_student(
            '2026/003', 'Peter', 'Otieno', self.cs_3a, Student.Status.ACTIVE
        )
        StudentParent.objects.create(student=self.s1, parent=self.parent)

        self.tuition = FeeCharge.objects.create(
            class_stream=self.cs_2a, term=self.term,
            description='Tuition', amount='20000.00',
        )
        self.activity = FeeCharge.objects.create(
            class_stream=self.cs_2a, term=self.term,
            description='Activity Fee', amount='2000.00',
        )

    def _make_user(self, username, role):
        user = User.objects.create_user(username)
        user.profile.role = role
        user.profile.save()
        return user

    def _make_student(self, admission_no, first, last, class_stream, status):
        return Student.objects.create(
            admission_no=admission_no, first_name=first, last_name=last,
            gender='M', date_of_birth='2011-01-01', class_stream=class_stream,
            date_admitted='2026-01-05', status=status,
        )

    def _login(self, user):
        self.client.force_login(user)

    def _account(self, student=None, term=None):
        return StudentFeeAccount.objects.create(
            student=student or self.s1, term=term or self.term,
        )

    def _charge(self, student=None, term=None, description='Tuition',
                amount='20000.00', fee_structure=None):
        return StudentCharge.objects.create(
            student=student or self.s1, term=term or self.term,
            description=description, amount=amount,
            fee_structure=fee_structure, created_by=self.admin,
        )

    def _payment(self, account=None, amount='10000.00', method='CASH',
                 receipt_no=None):
        return FeePayment.objects.create(
            account=account or self._account(), amount=amount,
            method=method, receipt_no=receipt_no, recorded_by=self.admin,
        )


class ModelConstraintTests(FeeBase):
    def test_fee_charge_amount_must_be_positive(self):
        charge = FeeCharge(
            class_stream=self.cs_2a, term=self.term,
            description='X', amount='0.00',
        )
        with self.assertRaises(ValidationError):
            charge.full_clean()

    def test_fee_charge_unique_per_class_term_description(self):
        with self.assertRaises(IntegrityError):
            FeeCharge.objects.create(
                class_stream=self.cs_2a, term=self.term,
                description='Tuition', amount='1.00',
            )

    def test_student_charge_amount_must_be_positive(self):
        charge = StudentCharge(
            student=self.s1, term=self.term,
            description='X', amount='0.00',
        )
        with self.assertRaises(ValidationError):
            charge.full_clean()

    def test_student_charge_negative_amount_rejected(self):
        charge = StudentCharge(
            student=self.s1, term=self.term,
            description='X', amount='-500.00',
        )
        with self.assertRaises(ValidationError):
            charge.full_clean()

    def test_student_charge_future_date_rejected(self):
        charge = self._charge()
        charge.date = localdate() + timedelta(days=5)
        with self.assertRaises(ValidationError):
            charge.full_clean()

    def test_student_charge_generated_duplicate_prevented(self):
        self._charge(fee_structure=self.tuition)
        with self.assertRaises(IntegrityError):
            self._charge(fee_structure=self.tuition)

    def test_manual_student_charge_same_description_allowed(self):
        first = self._charge(fee_structure=None)
        second = self._charge(
            description='Tuition', amount='5000.00', fee_structure=None
        )
        self.assertNotEqual(first.pk, second.pk)

    def test_payment_amount_must_be_positive(self):
        account = self._account()
        payment = FeePayment(account=account, amount='0.00')
        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_payment_negative_amount_rejected(self):
        account = self._account()
        payment = FeePayment(account=account, amount='-100.00')
        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_payment_future_date_rejected(self):
        account = self._account()
        payment = FeePayment(
            account=account, amount='100.00',
            date=localdate() + timedelta(days=5),
        )
        with self.assertRaises(ValidationError):
            payment.full_clean()

    def test_duplicate_receipt_rejected(self):
        account1 = self._account()
        account2 = self._account(student=self.s2)
        FeePayment.objects.create(
            account=account1, amount='100.00', receipt_no='R-100'
        )
        with self.assertRaises(IntegrityError):
            FeePayment.objects.create(
                account=account2, amount='50.00', receipt_no='R-100'
            )

    def test_payment_void_requires_reason(self):
        account = self._account()
        payment = FeePayment(
            account=account, amount='100.00', voided=True, void_reason='',
        )
        with self.assertRaises(ValidationError):
            payment.full_clean()


class BalanceAndAggregationTests(FeeBase):
    def test_balance_is_derived_charged_minus_paid(self):
        account = self._account()
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='12000.00', recorded_by=self.admin,
        )
        account.refresh_from_db()
        self.assertEqual(account.total_charged, 20000)
        self.assertEqual(account.total_paid, 12000)
        self.assertEqual(account.balance, 8000)
        self.assertFalse(account.in_credit)

    def test_overpayment_produces_credit(self):
        account = self._account()
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='10000.00', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='12000.00', recorded_by=self.admin,
        )
        self.assertEqual(account.balance, -2000)
        self.assertTrue(account.in_credit)

    def test_voided_payment_excluded_from_totals(self):
        account = self._account()
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='10000.00', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='6000.00', recorded_by=self.admin,
        )
        voided = FeePayment.objects.create(
            account=account, amount='5000.00', voided=True,
            void_reason='Duplicate', voided_by=self.admin,
        )
        self.assertTrue(voided.voided)
        self.assertEqual(account.total_paid, 6000)
        self.assertEqual(account.balance, 4000)

    def test_annotation_matches_property(self):
        account = self._account()
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='8000.00', recorded_by=self.admin,
        )
        annotated = annotate_account_totals(
            StudentFeeAccount.objects.filter(pk=account.pk)
        ).first()
        self.assertEqual(annotated.charged, 20000)
        self.assertEqual(annotated.paid, 8000)
        self.assertEqual(annotated.owed, 12000)

    def test_statement_running_balance_same_date_charges_first(self):
        account = self._account()
        day1 = date(2026, 2, 1)
        day2 = date(2026, 2, 10)
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', date=day1, created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='10000.00', date=day2, recorded_by=self.admin
        )
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Activity',
            amount='2000.00', date=day2, created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='5000.00', date=day2, recorded_by=self.admin
        )
        rows = charge_statement(account)
        kinds = [r['kind'] for r in rows]
        balances = [r['balance'] for r in rows]
        self.assertEqual(kinds, ['charge', 'charge', 'payment', 'payment'])
        self.assertEqual(balances, [20000, 22000, 12000, 7000])


class FeeStructureAdminTests(FeeBase):
    def test_admin_can_create_fee_structure_through_page(self):
        self._login(self.admin)
        response = self.client.post(reverse('fees:structure_add'), {
            'class_stream': self.cs_3a.pk,
            'term': self.term.pk,
            'description': 'Boarding',
            'amount': '15000.00',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            FeeCharge.objects.filter(
                class_stream=self.cs_3a, description='Boarding'
            ).exists()
        )

    def test_admin_can_edit_fee_structure(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:structure_edit', args=[self.tuition.pk]),
            {
                'class_stream': self.cs_2a.pk,
                'term': self.term.pk,
                'description': 'Tuition',
                'amount': '25000.00',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.tuition.refresh_from_db()
        self.assertEqual(self.tuition.amount, 25000)

    def test_admin_can_deactivate_fee_structure(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:structure_deactivate', args=[self.tuition.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.tuition.refresh_from_db()
        self.assertFalse(self.tuition.is_active)

    def test_structure_with_charges_cannot_be_deactivated(self):
        self._charge(fee_structure=self.tuition)
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:structure_deactivate', args=[self.tuition.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.tuition.refresh_from_db()
        self.assertTrue(self.tuition.is_active)

    def test_negative_fee_structure_rejected_through_page(self):
        self._login(self.admin)
        response = self.client.post(reverse('fees:structure_add'), {
            'class_stream': self.cs_3a.pk,
            'term': self.term.pk,
            'description': 'X',
            'amount': '-100.00',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Amount must be greater than zero')
        self.assertFalse(FeeCharge.objects.filter(description='X').exists())


class GenerateChargesTests(FeeBase):
    def test_generation_creates_charges_for_active_students(self):
        self._login(self.admin)
        response = self.client.post(reverse('fees:generate'), {
            'class_stream': self.cs_2a.pk,
            'term': self.term.pk,
        })
        self.assertEqual(response.status_code, 302)
        # 2 structures x 2 active students in cs_2a
        self.assertEqual(StudentCharge.objects.count(), 4)
        self.assertEqual(
            StudentCharge.objects.filter(
                student=self.s1, fee_structure=self.tuition
            ).count(),
            1,
        )

    def test_generation_is_idempotent(self):
        self._login(self.admin)
        for _ in range(2):
            response = self.client.post(reverse('fees:generate'), {
                'class_stream': self.cs_2a.pk,
                'term': self.term.pk,
            })
            self.assertEqual(response.status_code, 302)
        self.assertEqual(StudentCharge.objects.count(), 4)

    def test_generation_skips_inactive_students(self):
        self.s2.status = Student.Status.INACTIVE
        self.s2.save(update_fields=['status'])
        self._login(self.admin)
        self.client.post(reverse('fees:generate'), {
            'class_stream': self.cs_2a.pk,
            'term': self.term.pk,
        })
        self.assertEqual(
            StudentCharge.objects.filter(student=self.s1).count(), 2
        )
        self.assertFalse(
            StudentCharge.objects.filter(student=self.s2).exists()
        )

    def test_generation_updates_existing_charge_amount(self):
        self.tuition.amount = '30000.00'
        self.tuition.save(update_fields=['amount'])
        self._login(self.admin)
        self.client.post(reverse('fees:generate'), {
            'class_stream': self.cs_2a.pk,
            'term': self.term.pk,
        })
        charge = StudentCharge.objects.get(
            student=self.s1, fee_structure=self.tuition
        )
        self.assertEqual(charge.amount, 30000)
        self.assertEqual(StudentCharge.objects.count(), 4)


class ChargeWorkflowTests(FeeBase):
    def test_admin_can_add_charge_to_account(self):
        account = self._account()
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:charge_add', args=[account.pk]),
            {
                'description': 'Lab Fee',
                'amount': '1500.00',
                'date': '2026-02-15',
                'notes': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            StudentCharge.objects.filter(
                student=self.s1, term=self.term, description='Lab Fee'
            ).exists()
        )

    def test_admin_can_edit_charge(self):
        charge = self._charge(description='Tuition')
        account = StudentFeeAccount.objects.create(
            student=self.s1, term=self.term
        )
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:charge_edit', args=[charge.pk]),
            {
                'description': 'Tuition',
                'amount': '25000.00',
                'date': '2026-02-15',
                'notes': 'corrected',
            },
        )
        self.assertEqual(response.status_code, 302)
        charge.refresh_from_db()
        self.assertEqual(charge.amount, 25000)
        self.assertEqual(charge.notes, 'corrected')

    def test_charge_cannot_be_deleted(self):
        charge = self._charge()
        account = StudentFeeAccount.objects.create(
            student=self.s1, term=self.term
        )
        self._login(self.admin)
        delete_url = reverse('fees:charge_edit', args=[charge.pk]) + '/delete/'
        self.assertEqual(self.client.post(delete_url).status_code, 404)
        self.assertTrue(
            StudentCharge.objects.filter(pk=charge.pk).exists()
        )

    def test_teacher_cannot_manage_charges(self):
        account = self._account()
        self._login(self.teacher_user)
        response = self.client.get(
            reverse('fees:charge_add', args=[account.pk])
        )
        self.assertEqual(response.status_code, 403)


class PaymentWorkflowTests(FeeBase):
    def test_admin_can_record_payment(self):
        account = self._account()
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:payment_add', args=[account.pk]),
            {
                'amount': '5000.00',
                'method': 'MPESA',
                'receipt_no': 'R-001',
                'date': '2026-02-15',
                'notes': '',
            },
        )
        self.assertEqual(response.status_code, 302)
        payment = FeePayment.objects.get(receipt_no='R-001')
        self.assertEqual(payment.amount, 5000)
        self.assertEqual(payment.recorded_by, self.admin)
        self.assertEqual(payment.account, account)

    def test_admin_can_edit_payment_for_correction(self):
        payment = self._payment(amount='5000.00', receipt_no='R-001')
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:payment_edit', args=[payment.pk]),
            {
                'amount': '5500.00',
                'method': 'CASH',
                'receipt_no': 'R-001',
                'date': '2026-02-15',
                'notes': 'corrected amount',
            },
        )
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, 5500)
        self.assertEqual(payment.notes, 'corrected amount')

    def test_voided_payment_cannot_be_edited(self):
        payment = self._payment(amount='5000.00')
        payment.voided = True
        payment.void_reason = 'Wrong entry'
        payment.save()
        self._login(self.admin)
        response = self.client.get(
            reverse('fees:payment_edit', args=[payment.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_void_payment(self):
        payment = self._payment(amount='5000.00', receipt_no='R-002')
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:payment_void', args=[payment.pk]),
            {'void_reason': 'Cancel duplicate'},
        )
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        self.assertTrue(payment.voided)
        self.assertEqual(payment.void_reason, 'Cancel duplicate')
        self.assertEqual(payment.voided_by, self.admin)

    def test_void_requires_reason_through_page(self):
        payment = self._payment(amount='5000.00')
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:payment_void', args=[payment.pk]),
            {'void_reason': ''},
        )
        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertFalse(payment.voided)

    def test_voided_payment_stays_visible_in_history(self):
        payment = self._payment(amount='5000.00', receipt_no='R-003')
        payment.voided = True
        payment.void_reason = 'Duplicate'
        payment.save()
        self._login(self.admin)
        response = self.client.get(reverse('fees:payment_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'R-003')
        self.assertContains(response, 'VOIDED')

    def test_payment_cannot_be_deleted(self):
        payment = self._payment()
        self._login(self.admin)
        response = self.client.get(
            reverse('fees:payment_void', args=[payment.pk]) + '/delete/'
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(FeePayment.objects.filter(pk=payment.pk).exists())

    def test_invalid_payment_amount_rejected_through_page(self):
        account = self._account()
        self._login(self.admin)
        response = self.client.post(
            reverse('fees:payment_add', args=[account.pk]),
            {
                'amount': '-100.00',
                'method': 'CASH',
                'date': '2026-02-15',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Amount must be greater than zero')
        self.assertEqual(FeePayment.objects.count(), 0)


class DashboardAndHistoryTests(FeeBase):
    def test_dashboard_shows_totals(self):
        account = self._account()
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='8000.00', recorded_by=self.admin,
        )
        StudentCharge.objects.create(
            student=self.s2, term=self.term, description='Tuition',
            amount='20000.00', created_by=self.admin,
        )
        self._login(self.admin)
        response = self.client.get(reverse('fees:home'), {'term': self.term.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'KSh 40000.00')
        self.assertContains(response, 'KSh 8000.00')

    def test_dashboard_stats_service(self):
        stats = finance_dashboard_stats(term=self.term)
        self.assertEqual(stats['total_charged'], 0)
        self.assertEqual(stats['total_paid'], 0)
        self.assertEqual(stats['outstanding'], 0)
        self.assertEqual(stats['owing_count'], 0)

    def test_payment_history_filters_by_method(self):
        account = self._account()
        self._payment(account=account, method='CASH', receipt_no='R-A')
        self._payment(account=account, method='BANK', receipt_no='R-B')
        self._login(self.admin)
        response = self.client.get(
            reverse('fees:payment_list'), {'method': 'BANK'}
        )
        self.assertContains(response, 'R-B')
        self.assertNotContains(response, 'R-A')

    def test_payment_history_search(self):
        account = self._account()
        self._payment(account=account, receipt_no='R-SEARCH')
        self._login(self.admin)
        response = self.client.get(
            reverse('fees:payment_list'), {'q': 'R-SEARCH'}
        )
        self.assertContains(response, 'R-SEARCH')

    def test_account_list_shows_annotated_balances(self):
        account = self._account()
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='10000.00', recorded_by=self.admin,
        )
        self._login(self.admin)
        response = self.client.get(
            reverse('fees:accounts'), {'term': self.term.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'KSh 10000.00')
        self.assertContains(response, 'John Kamau')


class ParentAccessTests(FeeBase):
    def test_parent_can_view_own_children_finance(self):
        self._login(self.parent_user)
        response = self.client.get(reverse('fees:my_children'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')
        self.assertNotContains(response, 'Peter Otieno')

    def test_parent_can_view_linked_child_fees(self):
        self._login(self.parent_user)
        response = self.client.get(
            reverse('fees:child_fees', args=[self.s1.pk]),
            {'term': self.term.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')

    def test_parent_cannot_view_unlinked_child_fees(self):
        self._login(self.parent_user)
        response = self.client.get(
            reverse('fees:child_fees', args=[self.s3.pk]),
            {'term': self.term.pk},
        )
        self.assertEqual(response.status_code, 403)

    def test_child_fees_get_does_not_create_account(self):
        self._login(self.parent_user)
        response = self.client.get(
            reverse('fees:child_fees', args=[self.s1.pk]),
            {'term': self.term.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            StudentFeeAccount.objects.filter(
                student=self.s1, term=self.term
            ).exists()
        )

    def test_parent_cannot_post_charge(self):
        self._login(self.parent_user)
        response = self.client.post(reverse('fees:structure_add'), {
            'class_stream': self.cs_2a.pk,
            'term': self.term.pk,
            'description': 'X',
            'amount': '100.00',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(FeeCharge.objects.filter(description='X').exists())

    def test_parent_cannot_record_payment(self):
        account = self._account()
        self._login(self.parent_user)
        response = self.client.post(
            reverse('fees:payment_add', args=[account.pk]),
            {'amount': '100.00', 'method': 'CASH', 'date': '2026-02-15'},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(FeePayment.objects.count(), 0)

    def test_parent_sees_only_own_child_balance(self):
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', created_by=self.admin,
        )
        StudentCharge.objects.create(
            student=self.s3, term=self.term, description='Tuition',
            amount='30000.00', created_by=self.admin,
        )
        self._login(self.parent_user)
        response = self.client.get(reverse('fees:my_children'))
        self.assertContains(response, 'John Kamau')
        self.assertNotContains(response, 'Peter Otieno')


class TeacherAuthorizationTests(FeeBase):
    def test_teacher_gets_403_on_all_finance_urls(self):
        account = self._account()
        urls = [
            reverse('fees:home'),
            reverse('fees:structures'),
            reverse('fees:structure_add'),
            reverse('fees:accounts'),
            reverse('fees:account_detail', args=[account.pk]),
            reverse('fees:payment_list'),
            reverse('fees:charge_add', args=[account.pk]),
            reverse('fees:payment_add', args=[account.pk]),
            reverse('fees:generate'),
            reverse('fees:my_children'),
        ]
        self._login(self.teacher_user)
        responses = [self.client.get(url) for url in urls]
        for url, response in zip(urls, responses):
            self.assertEqual(
                response.status_code, 403,
                f'{url} returned {response.status_code} for teacher',
            )


class AnonymousAccessTests(FeeBase):
    def test_anonymous_redirected_to_login(self):
        account = self._account()
        urls = [
            reverse('fees:home'),
            reverse('fees:structures'),
            reverse('fees:structure_add'),
            reverse('fees:accounts'),
            reverse('fees:account_detail', args=[account.pk]),
            reverse('fees:payment_list'),
            reverse('fees:my_children'),
            reverse('fees:child_fees', args=[self.s1.pk]),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])


class HistoricalIntegrityTests(FeeBase):
    def test_charges_survive_student_deactivation(self):
        charge = self._charge()
        payment = self._payment(account=charge.student.fee_accounts.first())
        self.s1.status = Student.Status.GRADUATED
        self.s1.save(update_fields=['status'])
        self.assertEqual(
            StudentCharge.objects.filter(student=self.s1).count(), 1
        )
        self.assertEqual(
            FeePayment.objects.filter(account=payment.account).count(), 1
        )
        account = self.s1.fee_accounts.first()
        if account:
            self.assertTrue(account.total_charged >= Decimal(charge.amount))

    def test_payments_survive_recorded_by_deactivation(self):
        payment = self._payment(receipt_no='R-HIST')
        payment.recorded_by = self.teacher_user
        payment.save(update_fields=['recorded_by'])
        self.teacher.is_active = False
        self.teacher.save(update_fields=['is_active'])
        payment.refresh_from_db()
        self.assertEqual(payment.recorded_by, self.teacher.user)

    def test_student_delete_protected_by_charges(self):
        self._charge()
        with self.assertRaises(IntegrityError):
            self.s1.delete()

    def test_student_delete_protected_by_payment(self):
        self._payment()
        with self.assertRaises(IntegrityError):
            self.s1.delete()

    def test_parent_can_still_see_finance_after_student_inactive(self):
        self.s1.status = Student.Status.INACTIVE
        self.s1.save(update_fields=['status'])
        self._charge()
        account = self._account()
        FeePayment.objects.create(
            account=account, amount='5000.00', recorded_by=self.admin,
        )
        self._login(self.parent_user)
        response = self.client.get(reverse('fees:my_children'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')


class StatementAndParentPageTests(FeeBase):
    def test_statement_table_renders_on_admin_account_page(self):
        account = self.ensure_account_for_s1()
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', date='2026-02-01', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='10000.00', method='MPESA',
            date='2026-02-10', recorded_by=self.admin,
        )
        self._login(self.admin)
        response = self.client.get(
            reverse('fees:account_detail', args=[account.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tuition')
        self.assertContains(response, 'M-Pesa payment')

    def ensure_account_for_s1(self):
        account, _ = StudentFeeAccount.objects.get_or_create(
            student=self.s1, term=self.term
        )
        return account

    def test_child_fees_lists_payment_method_labels(self):
        account = self.ensure_account_for_s1()
        FeePayment.objects.create(
            account=account, amount='10000.00', method='MPESA',
            date='2026-02-10', recorded_by=self.admin,
        )
        self._login(self.parent_user)
        response = self.client.get(
            reverse('fees:child_fees', args=[self.s1.pk]),
            {'term': self.term.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'M-Pesa payment')

    def test_parent_children_finance_service_totals(self):
        account = self.ensure_account_for_s1()
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='12000.00', recorded_by=self.admin,
        )
        kids = parent_children_finance(self.parent)
        self.assertEqual(kids.count(), 1)
        child = kids.get(pk=self.s1.pk)
        self.assertEqual(child.total_charged, 20000)
        self.assertEqual(child.total_paid, 12000)
        self.assertEqual(child.balance, 8000)

    def test_account_lookup_opendocs(self):
        self._login(self.admin)
        response = self.client.post(reverse('fees:account_lookup'), {
            'student_q': '2026/001',
            'term': self.term.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            StudentFeeAccount.objects.filter(
                student=self.s1, term=self.term
            ).exists()
        )

    def test_migration_is_asset_clean(self):
        # ensures the generated migration is present and consistent
        call_command(
            'makemigrations', 'fees', '--check', '--dry-run',
            verbosity=0,
        )


class TechEdgeTests(FeeBase):
    def test_others_not_imported_from_core(self):
        """StudentCharge references students.Student, not core.Student."""
        charge = self._charge()
        self.assertEqual(charge.student, self.s1)
        self.assertIsInstance(charge.student, Student)


class EnrollmentFinanceTests(FeeBase):
    def setUp(self):
        super().setUp()
        record_admission(self.s1, start_date=self.s1.date_admitted)
        promote_student(
            actor=self.admin, student=self.s1,
            target_class_stream=self.cs_3a, effective_date=date(2026, 2, 20),
        )
        self.s1.refresh_from_db()
        self.boarding = FeeCharge.objects.create(
            class_stream=self.cs_3a, term=self.term,
            description='Boarding', amount='5000.00',
        )

    def _generate_all(self):
        generate_charges_for_class(self.cs_2a, self.term, self.admin)
        generate_charges_for_class(self.cs_3a, self.term, self.admin)

    def test_charges_generated_for_every_roster_overlap_in_term(self):
        self._generate_all()
        s1_charges = StudentCharge.objects.filter(
            student=self.s1, term=self.term
        )
        descriptions = set(s1_charges.values_list('description', flat=True))
        self.assertEqual(
            descriptions, {'Tuition', 'Activity Fee', 'Boarding'}
        )
        self.assertEqual(
            StudentCharge.objects.filter(
                student=self.s2, term=self.term
            ).count(),
            2,
        )

    def test_finance_dashboard_attributes_promotee_to_both_classes(self):
        self._generate_all()
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        self.assertEqual(float(stats_2a['total_charged']), 44000.0)
        self.assertEqual(float(stats_3a['total_charged']), 10000.0)
        self.assertEqual(stats_2a['owing_count'], 2)
        self.assertEqual(stats_3a['owing_count'], 2)

    def test_outstanding_accounts_respects_term_membership(self):
        self._generate_all()
        accounts_2a = outstanding_accounts(term=self.term, class_stream=self.cs_2a)
        accounts_3a = outstanding_accounts(term=self.term, class_stream=self.cs_3a)
        pk_2a = set(accounts_2a.values_list('student_id', flat=True))
        pk_3a = set(accounts_3a.values_list('student_id', flat=True))
        self.assertIn(self.s1.pk, pk_2a)
        self.assertIn(self.s1.pk, pk_3a)
        self.assertIn(self.s2.pk, pk_2a)
        self.assertNotIn(self.s2.pk, pk_3a)
        self.assertIn(self.s3.pk, pk_3a)


class ClassAttributionTests(EnrollmentFinanceTests):
    def _manual(self, student, day, amount, description='Manual Levy',
                term=None):
        return StudentCharge.objects.create(
            student=student, term=term or self.term, description=description,
            amount=amount, date=day, fee_structure=None, created_by=self.admin,
        )

    def _existing_account(self, student):
        return StudentFeeAccount.objects.get(student=student, term=self.term)

    def _payment(self, student, amount, day):
        return FeePayment.objects.create(
            account=self._existing_account(student), amount=amount, date=day,
            recorded_by=self.admin,
        )

    def test_no_charge_counted_twice_across_classes(self):
        self._generate_all()
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        whole = finance_dashboard_stats(self.term)
        self.assertEqual(
            stats_2a['total_charged'] + stats_3a['total_charged'],
            whole['total_charged'],
        )

    def test_manual_charge_attributed_by_enrollment_date(self):
        self._generate_all()
        self._manual(self.s1, date(2026, 2, 25), '1000.00')
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        self.assertEqual(float(stats_2a['total_charged']), 44000.0)
        self.assertEqual(float(stats_3a['total_charged']), 11000.0)

        self._manual(self.s1, date(2026, 2, 5), '500.00')
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        self.assertEqual(float(stats_2a['total_charged']), 44500.0)
        self.assertEqual(float(stats_3a['total_charged']), 11000.0)

    def test_manual_charge_legacy_fallback(self):
        self._generate_all()
        self._manual(self.s3, date(2026, 3, 1), '1000.00')
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        self.assertEqual(float(stats_2a['total_charged']), 44000.0)
        self.assertEqual(float(stats_3a['total_charged']), 11000.0)

    def test_single_class_student_attribution_unchanged(self):
        self._generate_all()
        FeePayment.objects.create(
            account=self._existing_account(self.s2), amount='10000.00',
            recorded_by=self.admin,
        )
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        whole = finance_dashboard_stats(self.term)
        self.assertEqual(float(stats_2a['total_paid']), 10000.0)
        self.assertEqual(float(stats_3a['total_paid']), 0.0)
        self.assertEqual(float(whole['total_paid']), 10000.0)
        self.assertEqual(
            stats_2a['total_charged'] + stats_3a['total_charged'],
            whole['total_charged'],
        )

    def test_fully_paid_account_before_promotion_reconciles_everywhere(self):
        self._generate_all()
        self._payment(self.s1, '27000.00', date(2026, 2, 1))
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        self.assertEqual(float(stats_2a['total_paid']), 22000.0)
        self.assertEqual(float(stats_3a['total_paid']), 5000.0)
        self.assertEqual(float(stats_2a['outstanding']), 22000.0)
        self.assertEqual(float(stats_3a['outstanding']), 5000.0)
        self.assertEqual(
            stats_2a['paid_full_count'], 1,
        )

    def test_partially_paid_account_proportional_allocation(self):
        self._generate_all()
        self._payment(self.s1, '2700.00', date(2026, 2, 25))
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        self.assertEqual(float(stats_2a['total_paid']), 2200.0)
        self.assertEqual(float(stats_3a['total_paid']), 500.0)
        s2a = outstanding_accounts(term=self.term, class_stream=self.cs_2a).get(
            student_id=self.s1.pk
        )
        self.assertEqual(float(s2a.owed), 19800.0)
        s3a = outstanding_accounts(term=self.term, class_stream=self.cs_3a).get(
            student_id=self.s1.pk
        )
        self.assertEqual(float(s3a.owed), 4500.0)
        self.assertAlmostEqual(
            float(s2a.owed) + float(s3a.owed), 24300.0,
        )

    def test_multiple_payments_allocated_once_across_classes(self):
        self._generate_all()
        self._payment(self.s1, '2000.00', date(2026, 2, 25))
        self._payment(self.s1, '700.00', date(2026, 3, 5))
        whole = finance_dashboard_stats(self.term)
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        self.assertEqual(float(whole['total_paid']), 2700.0)
        self.assertEqual(float(stats_2a['total_paid']), 2200.0)
        self.assertEqual(float(stats_3a['total_paid']), 500.0)
        self.assertEqual(
            stats_2a['total_paid'] + stats_3a['total_paid'], whole['total_paid'],
        )

    def test_zero_charge_payment_fallback(self):
        self._generate_all()
        s4 = self._make_student(
            '2026/004', 'Grace', 'Achieng', self.cs_3a, Student.Status.ACTIVE
        )
        account = self._account(student=s4)
        FeePayment.objects.create(
            account=account, amount='1500.00', date=date(2026, 3, 10),
            recorded_by=self.admin,
        )
        stats_2a = finance_dashboard_stats(self.term, self.cs_2a)
        stats_3a = finance_dashboard_stats(self.term, self.cs_3a)
        whole = finance_dashboard_stats(self.term)
        self.assertEqual(float(stats_2a['total_paid']), 0.0)
        self.assertEqual(float(stats_3a['total_paid']), 1500.0)
        self.assertEqual(float(whole['total_paid']), 1500.0)

    def test_outstanding_accounts_class_sliced_balances(self):
        self._generate_all()
        self._payment(self.s1, '2700.00', date(2026, 2, 25))
        owed_2a = {
            row.student_id: float(row.owed)
            for row in outstanding_accounts(
                term=self.term, class_stream=self.cs_2a
            )
        }
        owed_3a = {
            row.student_id: float(row.owed)
            for row in outstanding_accounts(
                term=self.term, class_stream=self.cs_3a
            )
        }
        self.assertEqual(owed_2a[self.s1.pk], 19800.0)
        self.assertEqual(owed_2a[self.s2.pk], 22000.0)
        self.assertEqual(owed_3a[self.s1.pk], 4500.0)
        self.assertEqual(owed_3a[self.s3.pk], 5000.0)
        self.assertNotIn(self.s2.pk, owed_3a)
        whole = finance_dashboard_stats(self.term)
        self.assertEqual(
            sum(owed_2a.values()) + sum(owed_3a.values()),
            float(whole['total_charged']) - float(whole['total_paid']),
        )

    def test_account_list_view_class_filter_slices_balances(self):
        self._generate_all()
        self._payment(self.s1, '2700.00', date(2026, 2, 25))
        self._login(self.admin)
        url_2a = reverse('fees:accounts')
        response = self.client.get(url_2a, {
            'class_stream': self.cs_2a.pk, 'term': self.term.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'KSh 22000.00')
        self.assertContains(response, 'KSh 19800.00')
        response = self.client.get(url_2a, {
            'class_stream': self.cs_3a.pk, 'term': self.term.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'KSh 5000.00')
        self.assertContains(response, 'KSh 4500.00')

    def test_account_list_view_whole_school_unchanged(self):
        self._generate_all()
        self._payment(self.s1, '2700.00', date(2026, 2, 25))
        self._login(self.admin)
        response = self.client.get(reverse('fees:accounts'), {
            'term': self.term.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'KSh 27000.00')
        self.assertContains(response, 'KSh 24300.00')
        self.assertContains(response, 'KSh 22000.00')