from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils.timezone import localdate

from attendance.models import Attendance
from attendance.services import status_counts
from core.models import (
    AcademicYear,
    ClassStream,
    Department,
    SchoolClass,
    Stream,
    Subject,
    Teacher,
    TeacherAssignment,
    Term,
)
from core.services import teacher_authorized_attendance_streams
from students.models import Parent, Student, StudentParent
from students.services import promote_student, record_admission


class AttendanceAccessBase(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            name='2026', start_date='2026-01-01', end_date='2026-12-31',
            is_current=True,
        )
        self.term = Term.objects.create(
            name='Term 1', year=self.year, start_date='2026-01-10',
            end_date='2026-04-10', is_current=True,
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
        self.math = Subject.objects.create(name='Mathematics', code='MAT')
        self.dept = Department.objects.create(name='Science', code='SCI')

        self.admin = self._make_user('admin', 'ADMIN')

        self.teacher_user = self._make_user('teacher1', 'TEACHER')
        self.teacher = self._make_teacher(
            'T001', 'John', 'Kamau', user=self.teacher_user
        )
        TeacherAssignment.objects.create(
            teacher=self.teacher, class_stream=self.cs_2a, subject=self.math
        )

        self.ct_user = self._make_user('classteacher', 'TEACHER')
        self.class_teacher = self._make_teacher(
            'T002', 'Grace', 'Wanjiru', user=self.ct_user
        )
        self.cs_2a.class_teacher = self.class_teacher
        self.cs_2a.save(update_fields=['class_teacher'])

        self.parent_user = self._make_user('parent1', 'PARENT')
        self.parent = Parent.objects.create(
            user=self.parent_user, first_name='Mary', last_name='Wanjiru',
            phone='0700000000',
        )

        self.s1 = Student.objects.create(
            admission_no='2026/001', first_name='John', last_name='Kamau',
            gender='M', date_of_birth='2011-01-01', class_stream=self.cs_2a,
            date_admitted='2026-01-05', status=Student.Status.ACTIVE,
        )
        self.s2 = Student.objects.create(
            admission_no='2026/002', first_name='Mary', last_name='Wanjiku',
            gender='F', date_of_birth='2011-02-01', class_stream=self.cs_2a,
            date_admitted='2026-01-05', status=Student.Status.ACTIVE,
        )
        self.s3 = Student.objects.create(
            admission_no='2026/003', first_name='Peter', last_name='Otieno',
            gender='M', date_of_birth='2010-05-01', class_stream=self.cs_3a,
            date_admitted='2026-01-05', status=Student.Status.ACTIVE,
        )
        StudentParent.objects.create(student=self.s1, parent=self.parent)

        self.past = localdate() - timedelta(days=7)
        self.future = localdate() + timedelta(days=7)
        self.in_term = date(2026, 2, 10)
        self.out_term = date(2026, 6, 10)

    def _make_user(self, username, role):
        user = User.objects.create_user(username)
        user.profile.role = role
        user.profile.save()
        return user

    def _make_teacher(self, employee_no, first, last, user=None):
        return Teacher.objects.create(
            user=user, employee_no=employee_no, first_name=first,
            last_name=last, gender='M', date_joined='2024-01-10',
            department=self.dept,
        )

    def _login(self, user):
        self.client.force_login(user)

    def _sheet_url(self, class_stream, date):
        return (
            reverse('attendance:sheet')
            + f'?class_stream={class_stream.pk}&date={date.isoformat()}'
        )

    def _payload(self, class_stream, statuses):
        students = Student.objects.filter(
            class_stream=class_stream, status=Student.Status.ACTIVE
        ).order_by('admission_no')
        payload = {
            'form-TOTAL_FORMS': str(students.count()),
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        for index, student in enumerate(students):
            payload[f'form-{index}-student'] = student.pk
            payload[f'form-{index}-status'] = statuses.get(
                student.pk, Attendance.Status.PRESENT
            )
        return payload


class TeacherAuthorizationTests(AttendanceAccessBase):
    def test_class_teacher_can_take_attendance(self):
        self._login(self.ct_user)
        response = self.client.post(
            self._sheet_url(self.cs_2a, self.past),
            self._payload(self.cs_2a, {self.s1.pk: Attendance.Status.ABSENT}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Attendance.objects.filter(class_stream=self.cs_2a, date=self.past).count(), 2
        )
        self.assertEqual(
            Attendance.objects.get(student=self.s1, date=self.past).status,
            Attendance.Status.ABSENT,
        )

    def test_subject_teacher_without_class_teacher_gets_403(self):
        self._login(self.teacher_user)
        response = self.client.get(self._sheet_url(self.cs_2a, self.past))
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            self._sheet_url(self.cs_2a, self.past),
            self._payload(self.cs_2a, {}),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_unauthorized_teacher_cannot_write(self):
        self._login(self.teacher_user)
        response = self.client.post(
            self._sheet_url(self.cs_3a, self.past),
            self._payload(self.cs_3a, {self.s3.pk: Attendance.Status.PRESENT}),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_class_teacher_cannot_write_other_stream(self):
        self._login(self.ct_user)
        response = self.client.get(self._sheet_url(self.cs_3a, self.past))
        self.assertEqual(response.status_code, 403)

    def test_attendance_streams_service_returns_class_teacher_only(self):
        self.assertFalse(teacher_authorized_attendance_streams(self.teacher).exists())
        streams = teacher_authorized_attendance_streams(self.class_teacher)
        self.assertEqual(list(streams), [self.cs_2a])

    def test_subject_teacher_cannot_read_student_page_outside_attendance_scope(self):
        self._login(self.teacher_user)
        response = self.client.get(reverse('attendance:student', args=[self.s1.pk]))
        self.assertEqual(response.status_code, 403)

    def test_class_teacher_can_read_student_page(self):
        self._login(self.ct_user)
        response = self.client.get(reverse('attendance:student', args=[self.s1.pk]))
        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_view_out_of_scope_student(self):
        self._login(self.teacher_user)
        response = self.client.get(reverse('attendance:student', args=[self.s3.pk]))
        self.assertEqual(response.status_code, 403)


class AdminAndParentTests(AttendanceAccessBase):
    def test_admin_can_take_attendance_any_stream(self):
        self._login(self.admin)
        response = self.client.post(
            self._sheet_url(self.cs_3a, self.past),
            self._payload(self.cs_3a, {self.s3.pk: Attendance.Status.PRESENT}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Attendance.objects.filter(student=self.s3, date=self.past).exists()
        )

    def test_admin_can_open_sheet_for_stream_without_class_teacher(self):
        self._login(self.admin)
        response = self.client.get(self._sheet_url(self.cs_3a, self.past))
        self.assertEqual(response.status_code, 200)

    def test_parent_cannot_write_attendance(self):
        self._login(self.parent_user)
        response = self.client.post(
            self._sheet_url(self.cs_2a, self.past),
            self._payload(self.cs_2a, {self.s1.pk: Attendance.Status.PRESENT}),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_parent_can_view_own_children(self):
        self._login(self.parent_user)
        response = self.client.get(reverse('attendance:my_children'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')
        self.assertNotContains(response, 'Peter Otieno')

    def test_parent_can_view_linked_child_page(self):
        self._login(self.parent_user)
        response = self.client.get(reverse('attendance:student', args=[self.s1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')

    def test_parent_cannot_view_unlinked_child_page(self):
        self._login(self.parent_user)
        response = self.client.get(reverse('attendance:student', args=[self.s3.pk]))
        self.assertEqual(response.status_code, 403)


class AttendanceSheetTests(AttendanceAccessBase):
    def test_bulk_save_works(self):
        self._login(self.ct_user)
        response = self.client.post(
            self._sheet_url(self.cs_2a, self.past),
            self._payload(self.cs_2a, {
                self.s1.pk: Attendance.Status.ABSENT,
                self.s2.pk: Attendance.Status.LATE,
            }),
        )
        self.assertEqual(response.status_code, 302)
        records = Attendance.objects.filter(date=self.past).values('student_id', 'status')
        by_student = {row['student_id']: row['status'] for row in records}
        self.assertEqual(by_student[self.s1.pk], Attendance.Status.ABSENT)
        self.assertEqual(by_student[self.s2.pk], Attendance.Status.LATE)

    def test_editing_existing_sheet_does_not_duplicate_rows(self):
        self._login(self.ct_user)
        self.client.post(
            self._sheet_url(self.cs_2a, self.past),
            self._payload(self.cs_2a, {self.s1.pk: Attendance.Status.PRESENT}),
        )
        self.assertEqual(Attendance.objects.filter(date=self.past).count(), 2)
        response = self.client.post(
            self._sheet_url(self.cs_2a, self.past),
            self._payload(self.cs_2a, {self.s1.pk: Attendance.Status.LATE}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attendance.objects.filter(date=self.past).count(), 2)
        self.assertEqual(
            Attendance.objects.get(student=self.s1, date=self.past).status,
            Attendance.Status.LATE,
        )

    def test_invalid_status_rejected(self):
        self._login(self.ct_user)
        payload = self._payload(self.cs_2a, {self.s1.pk: 'NOT_A_STATUS'})
        response = self.client.post(self._sheet_url(self.cs_2a, self.past), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a valid choice')
        self.assertEqual(Attendance.objects.filter(date=self.past).count(), 0)

    def test_student_from_other_stream_rejected_in_sheet(self):
        self._login(self.ct_user)
        payload = self._payload(self.cs_2a, {self.s1.pk: Attendance.Status.PRESENT})
        payload['form-1-student'] = self.s3.pk
        response = self.client.post(self._sheet_url(self.cs_2a, self.past), payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a valid choice')
        self.assertEqual(Attendance.objects.filter(date=self.past).count(), 0)

    def test_model_rejects_student_stream_mismatch(self):
        record = Attendance(
            student=self.s3, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.PRESENT,
        )
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_future_date_rejected(self):
        self._login(self.ct_user)
        response = self.client.post(
            self._sheet_url(self.cs_2a, self.future),
            self._payload(self.cs_2a, {self.s1.pk: Attendance.Status.PRESENT}),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'future')
        self.assertEqual(Attendance.objects.filter(date=self.future).count(), 0)

    def test_future_date_rejected_on_get(self):
        self._login(self.ct_user)
        response = self.client.get(self._sheet_url(self.cs_2a, self.future))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'future')

    def test_duplicate_attendance_prevented(self):
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.PRESENT,
        )
        with self.assertRaises(IntegrityError):
            Attendance.objects.create(
                student=self.s1, class_stream=self.cs_2a, date=self.past,
                status=Attendance.Status.ABSENT,
            )

    def test_notes_field_blank_by_default(self):
        record = Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.PRESENT,
        )
        self.assertEqual(record.notes, '')


class PercentageAndHistoryTests(AttendanceAccessBase):
    def _seed_percentage(self):
        dates = [self.past, self.in_term, self.out_term, date(2026, 3, 5), date(2026, 3, 6)]
        statuses = [
            Attendance.Status.PRESENT,
            Attendance.Status.PRESENT,
            Attendance.Status.PRESENT,
            Attendance.Status.ABSENT,
            Attendance.Status.LATE,
        ]
        for day, status in zip(dates, statuses):
            Attendance.objects.create(
                student=self.s1, class_stream=self.cs_2a, date=day, status=status,
            )

    def test_percentage_calculation(self):
        self._seed_percentage()
        summary = status_counts(self.s1.attendance.all())
        self.assertEqual(summary['total'], 5)
        self.assertEqual(summary['counts']['PRESENT'], 3)
        self.assertEqual(summary['counts']['ABSENT'], 1)
        self.assertEqual(summary['counts']['LATE'], 1)
        self.assertEqual(summary['percent'], 60.0)

    def test_parent_sees_percentage_on_student_page(self):
        self._seed_percentage()
        self._login(self.parent_user)
        response = self.client.get(reverse('attendance:student', args=[self.s1.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '60.0')

    def test_history_filter_by_term(self):
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a, date=self.in_term,
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            student=self.s2, class_stream=self.cs_2a, date=self.out_term,
            status=Attendance.Status.ABSENT,
        )
        self._login(self.admin)
        response = self.client.get(
            reverse('attendance:history'), {'term': self.term.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2026/001')
        self.assertNotContains(response, '2026/002')

    def test_history_filter_by_status_and_date(self):
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.ABSENT,
        )
        self._login(self.admin)
        response = self.client.get(
            reverse('attendance:history'),
            {'status': Attendance.Status.PRESENT, 'date_from': self.in_term.isoformat()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No attendance records match the current filters.')
        self.assertNotContains(response, '2026/001')

    def test_teacher_history_scoped_to_own_class_stream(self):
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            student=self.s3, class_stream=self.cs_3a, date=self.past,
            status=Attendance.Status.PRESENT,
        )
        self._login(self.ct_user)
        response = self.client.get(reverse('attendance:history'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')
        self.assertNotContains(response, 'Peter Otieno')

    def test_admin_history_shows_all_streams(self):
        Attendance.objects.create(
            student=self.s3, class_stream=self.cs_3a, date=self.past,
            status=Attendance.Status.PRESENT,
        )
        self._login(self.admin)
        response = self.client.get(reverse('attendance:history'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Peter Otieno')

    def test_parent_cannot_open_history(self):
        self._login(self.parent_user)
        response = self.client.get(reverse('attendance:history'))
        self.assertEqual(response.status_code, 403)


class HistoricalIntegrityTests(AttendanceAccessBase):
    def test_attendance_survives_student_deactivation(self):
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.ABSENT,
        )
        Attendance.objects.create(
            student=self.s2, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.PRESENT,
        )
        self.s1.status = Student.Status.TRANSFERRED
        self.s1.save(update_fields=['status'])
        self.assertEqual(Attendance.objects.filter(date=self.past).count(), 2)
        summary = status_counts(self.s1.attendance.all())
        self.assertEqual(summary['counts']['ABSENT'], 1)

    def test_inactive_student_not_in_new_sheet_roster(self):
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.PRESENT,
        )
        self.s1.status = Student.Status.INACTIVE
        self.s1.save(update_fields=['status'])
        self._login(self.ct_user)
        response = self.client.post(
            self._sheet_url(self.cs_2a, self.past),
            self._payload(self.cs_2a, {self.s2.pk: Attendance.Status.ABSENT}),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Attendance.objects.filter(date=self.past).count(), 2)
        self.assertEqual(
            Attendance.objects.get(student=self.s1, date=self.past).status,
            Attendance.Status.PRESENT,
        )
        self.assertEqual(
            Attendance.objects.get(student=self.s2, date=self.past).status,
            Attendance.Status.ABSENT,
        )

    def test_attendance_survives_teacher_deactivation(self):
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a, date=self.past,
            status=Attendance.Status.PRESENT, recorded_by=self.ct_user,
        )
        self.class_teacher.is_active = False
        self.class_teacher.save(update_fields=['is_active'])
        record = Attendance.objects.get(student=self.s1, date=self.past)
        self.assertEqual(record.status, Attendance.Status.PRESENT)
        self.assertEqual(record.recorded_by, self.ct_user)


class AnonymousAccessTests(AttendanceAccessBase):
    def test_anonymous_redirected_to_login(self):
        urls = [
            reverse('attendance:home'),
            reverse('attendance:take'),
            reverse('attendance:history'),
            reverse('attendance:my_children'),
            reverse('attendance:student', args=[self.s1.pk]),
            self._sheet_url(self.cs_2a, self.past),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])


class EnrollmentHistoricalAttendanceTests(AttendanceAccessBase):
    def setUp(self):
        super().setUp()
        record_admission(self.s1, start_date=self.s1.date_admitted)
        promote_student(
            actor=self.admin, student=self.s1,
            target_class_stream=self.cs_3a, effective_date=date(2026, 2, 20),
        )
        self.s1.refresh_from_db()

    def _record(self, class_stream, day):
        return Attendance(
            student=self.s1, class_stream=class_stream, date=day,
            status=Attendance.Status.PRESENT,
        )

    def test_attendance_valid_in_old_class_before_promotion(self):
        record = self._record(self.cs_2a, date(2026, 2, 10))
        record.full_clean()
        record.save()
        self.assertEqual(Attendance.objects.filter(student=self.s1).count(), 1)

    def test_attendance_valid_in_new_class_after_promotion(self):
        record = self._record(self.cs_3a, date(2026, 3, 10))
        record.full_clean()
        record.save()
        self.assertEqual(Attendance.objects.filter(student=self.s1).count(), 1)

    def test_attendance_rejected_in_old_class_after_promotion(self):
        with self.assertRaises(ValidationError):
            self._record(self.cs_2a, date(2026, 3, 10)).full_clean()

    def test_sheet_roster_follows_membership_by_date(self):
        self._login(self.admin)
        old_sheet = self.client.get(self._sheet_url(self.cs_2a, date(2026, 2, 10)))
        self.assertEqual(old_sheet.status_code, 200)
        self.assertContains(old_sheet, 'John Kamau')
        late_sheet = self.client.get(self._sheet_url(self.cs_2a, date(2026, 3, 10)))
        self.assertEqual(late_sheet.status_code, 200)
        self.assertNotContains(late_sheet, 'John Kamau')
        new_sheet = self.client.get(self._sheet_url(self.cs_3a, date(2026, 3, 10)))
        self.assertEqual(new_sheet.status_code, 200)
        self.assertContains(new_sheet, 'John Kamau')