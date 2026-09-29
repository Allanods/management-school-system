from datetime import date
import importlib

from django.apps import apps as global_apps
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from academics.models import Assessment, Mark
from core.models import (
    AcademicYear,
    ClassStream,
    SchoolClass,
    Stream,
    Subject,
    Teacher,
    TeacherAssignment,
    Term,
)
from students.models import (
    EnrollmentReason,
    Parent,
    Student,
    StudentEnrollment,
    StudentParent,
)
from students.services import (
    correct_enrollment,
    get_class_roster,
    get_class_roster_for_term,
    promote_student,
    promote_students,
    record_admission,
    record_class_change,
    student_in_class,
    validate_promotion,
)


class StudentAccessBase(TestCase):
    def setUp(self):
        self.klass = SchoolClass.objects.create(name='Form 2')
        self.stream_a = Stream.objects.create(name='A')
        self.stream_b = Stream.objects.create(name='B')
        self.cs_a = ClassStream.objects.create(
            school_class=self.klass, stream=self.stream_a
        )
        self.cs_b = ClassStream.objects.create(
            school_class=self.klass, stream=self.stream_b
        )
        self.subject = Subject.objects.create(name='Mathematics', code='MAT')

        self.admin = self._make_user('admin', 'ADMIN')

        self.teacher_user = self._make_user('teacher1', 'TEACHER')
        self.teacher = Teacher.objects.create(
            user=self.teacher_user,
            employee_no='T001',
            first_name='John',
            last_name='Kamau',
            gender='M',
            date_joined='2024-01-10',
        )
        TeacherAssignment.objects.create(
            teacher=self.teacher, class_stream=self.cs_a, subject=self.subject
        )

        self.parent1_user = self._make_user('parent1', 'PARENT')
        self.parent1 = Parent.objects.create(
            user=self.parent1_user, first_name='Jane', last_name='Otieno',
            phone='0711111111',
        )
        self.parent2_user = self._make_user('parent2', 'PARENT')
        self.parent2 = Parent.objects.create(
            user=self.parent2_user, first_name='Mary', last_name='Wanjiku',
            phone='0722222222',
        )

        self.student_a = self._make_student(
            '2026/001', 'Brian', 'Otieno', self.cs_a, self.parent1
        )
        self.student_b = self._make_student(
            '2026/002', 'Kevin', 'Mwangi', self.cs_b, self.parent2
        )

    def _make_user(self, username, role):
        user = User.objects.create_user(username)
        user.profile.role = role
        user.profile.save()
        return user

    def _make_student(self, adm, first, last, class_stream, parent):
        student = Student.objects.create(
            admission_no=adm,
            first_name=first,
            last_name=last,
            gender='M',
            date_of_birth='2010-05-10',
            class_stream=class_stream,
            date_admitted='2026-01-10',
            status=Student.Status.ACTIVE,
        )
        StudentParent.objects.create(
            student=student, parent=parent, relationship=StudentParent.Relationship.GUARDIAN
        )
        return student

    def _student_data(self, adm='2026/009', cs=None, status='ACTIVE'):
        return {
            'admission_no': adm,
            'first_name': 'Faith',
            'middle_name': '',
            'last_name': 'Njuguna',
            'gender': 'F',
            'date_of_birth': '2011-03-15',
            'class_stream': (cs or self.cs_a).id,
            'date_admitted': '2026-02-02',
            'status': status,
            'contact_name': '',
            'contact_phone': '',
        }

    def _create_mark(self, student):
        year = AcademicYear.objects.create(
            name='2026', start_date='2026-01-01', end_date='2026-12-31'
        )
        term = Term.objects.create(
            name='Term 1', year=year, start_date='2026-01-10', end_date='2026-04-10'
        )
        assessment = Assessment.objects.create(
            name='CAT 1', term=term, class_stream=self.cs_a, subject=self.subject
        )
        Mark.objects.create(
            student=student, assessment=assessment, subject=self.subject, scored=78
        )


class AnonymousAccessTests(StudentAccessBase):
    def test_anonymous_redirected_to_login(self):
        urls = [
            reverse('students:list'),
            reverse('students:add'),
            reverse('students:detail', args=[self.student_a.pk]),
            reverse('students:edit', args=[self.student_a.pk]),
            reverse('students:my_children'),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])


class AdminCrudTests(StudentAccessBase):
    def test_admin_can_create_student(self):
        self.client.force_login(self.admin)
        data = self._student_data()
        response = self.client.post(reverse('students:add'), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Student.objects.filter(admission_no='2026/009').exists())

    def test_admin_can_edit_student(self):
        self.client.force_login(self.admin)
        data = self._student_data(
            adm=self.student_a.admission_no,
            cs=self.student_a.class_stream,
            status=Student.Status.SUSPENDED,
        )
        data['first_name'] = 'Brian James'
        response = self.client.post(
            reverse('students:edit', args=[self.student_a.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.student_a.refresh_from_db()
        self.assertEqual(self.student_a.first_name, 'Brian James')
        self.assertEqual(self.student_a.status, Student.Status.SUSPENDED)

    def test_duplicate_admission_number_rejected(self):
        self.client.force_login(self.admin)
        data = self._student_data(adm=self.student_a.admission_no)
        response = self.client.post(reverse('students:add'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(Student.objects.count(), 2)

    def test_non_admin_cannot_add_or_edit(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(
            self.client.get(reverse('students:add')).status_code, 403
        )
        self.assertEqual(
            self.client.get(
                reverse('students:edit', args=[self.student_a.pk])
            ).status_code,
            403,
        )

    def test_inactive_status_keeps_student_and_blocks_deletion(self):
        self._create_mark(self.student_a)
        self.client.force_login(self.admin)
        data = self._student_data(
            adm=self.student_a.admission_no,
            cs=self.student_a.class_stream,
            status=Student.Status.INACTIVE,
        )
        response = self.client.post(
            reverse('students:edit', args=[self.student_a.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.student_a.refresh_from_db()
        self.assertEqual(self.student_a.status, Student.Status.INACTIVE)
        self.assertTrue(Student.objects.filter(pk=self.student_a.pk).exists())
        with self.assertRaises(ProtectedError):
            self.student_a.delete()


class TeacherAccessTests(StudentAccessBase):
    def test_teacher_sees_only_authorized_students(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('students:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Brian Otieno')
        self.assertNotContains(response, 'Kevin Mwangi')

    def test_teacher_can_view_authorized_student_detail(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(
            reverse('students:detail', args=[self.student_a.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_view_unauthorized_student(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(
            reverse('students:detail', args=[self.student_b.pk])
        )
        self.assertEqual(response.status_code, 403)


class ParentAccessTests(StudentAccessBase):
    def test_parent_can_view_linked_child(self):
        self.client.force_login(self.parent1_user)
        response = self.client.get(
            reverse('students:detail', args=[self.student_a.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_parent_cannot_view_another_parent_child(self):
        self.client.force_login(self.parent1_user)
        response = self.client.get(
            reverse('students:detail', args=[self.student_b.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_parent_sees_only_own_children(self):
        self.client.force_login(self.parent1_user)
        response = self.client.get(reverse('students:my_children'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Brian Otieno')
        self.assertNotContains(response, 'Kevin Mwangi')

    def test_parent_cannot_use_student_list(self):
        self.client.force_login(self.parent1_user)
        response = self.client.get(reverse('students:list'))
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_edit_student(self):
        self.client.force_login(self.parent1_user)
        response = self.client.get(
            reverse('students:edit', args=[self.student_a.pk])
        )
        self.assertEqual(response.status_code, 403)


class ParentRecordTests(StudentAccessBase):
    def _parent_data(self, **overrides):
        data = {
            'first_name': 'George',
            'last_name': 'Odinga',
            'phone': '0733333333',
            'email': 'george@example.com',
            'occupation': 'Engineer',
            'address': 'Nairobi',
        }
        data.update(overrides)
        return data

    def test_anonymous_redirected_on_parent_pages(self):
        for url in [
            reverse('students:parent_list'),
            reverse('students:parent_add'),
            reverse('students:parent_detail', args=[self.parent1.pk]),
            reverse('students:parent_edit', args=[self.parent1.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])

    def test_only_admin_can_manage_parent_records(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(
            self.client.get(reverse('students:parent_list')).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse('students:parent_add')).status_code, 403
        )
        self.assertEqual(
            self.client.get(
                reverse('students:parent_edit', args=[self.parent1.pk])
            ).status_code,
            403,
        )

    def test_admin_list_filters_unlinked(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('students:parent_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Jane Otieno')
        self.assertContains(response, 'Mary Wanjiku')

        unlinked = Parent.objects.create(
            first_name='Paul', last_name='Kimani', phone='0700000000'
        )
        response = self.client.get(
            reverse('students:parent_list') + '?linked=unlinked'
        )
        self.assertContains(response, 'Paul Kimani')
        self.assertNotContains(response, 'Jane Otieno')

    def test_unlinked_parent_banner_shown_to_admin(self):
        self.client.force_login(self.admin)
        Parent.objects.create(
            first_name='Paul', last_name='Kimani', phone='0700000000'
        )
        response = self.client.get(reverse('students:parent_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no user account yet')

    def test_admin_can_create_parent(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('students:parent_add'), self._parent_data()
        )
        self.assertEqual(response.status_code, 302)
        parent = Parent.objects.get(first_name='George')
        self.assertEqual(parent.last_name, 'Odinga')
        self.assertIsNone(parent.user)

    def test_admin_can_edit_parent(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('students:parent_edit', args=[self.parent1.pk]),
            self._parent_data(first_name='Jane', last_name='Otieno', phone='0799999999'),
        )
        self.assertEqual(response.status_code, 302)
        self.parent1.refresh_from_db()
        self.assertEqual(self.parent1.phone, '0799999999')
        self.assertEqual(self.parent1.user, self.parent1_user)

    def test_parent_can_view_own_profile_only(self):
        self.client.force_login(self.parent1_user)
        response = self.client.get(
            reverse('students:parent_detail', args=[self.parent1.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Brian Otieno')

    def test_parent_cannot_view_other_parent(self):
        self.client.force_login(self.parent1_user)
        response = self.client.get(
            reverse('students:parent_detail', args=[self.parent2.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_view_parent(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(
            reverse('students:parent_detail', args=[self.parent1.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_provision_account_flow_after_parent_crud(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse('students:parent_add'), self._parent_data()
        )
        parent = Parent.objects.get(first_name='George')
        url = reverse('accounts:user_add') + '?role=PARENT'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="PARENT"')
        response = self.client.post(url, {
            'role': 'PARENT',
            'username': 'george_p',
            'email': 'george@example.com',
            'password1': 'SecurePass123!',
            'password2': 'SecurePass123!',
            'parent': parent.pk,
        })
        self.assertEqual(response.status_code, 302)
        parent.refresh_from_db()
        self.assertIsNotNone(parent.user)
        self.assertEqual(parent.user.username, 'george_p')


class StudentEnrollmentModelTests(StudentAccessBase):
    def setUp(self):
        super().setUp()
        self.student = self._make_student(
            '2026/003', 'Tara', 'Njeri', self.cs_a, self.parent1
        )

    def test_enrollment_requires_end_after_start(self):
        with self.assertRaises(ValidationError):
            StudentEnrollment.objects.create(
                student=self.student, class_stream=self.cs_a,
                start_date=date(2026, 3, 1), end_date=date(2026, 2, 1),
            )

    def test_backward_window_rejected_even_when_closed(self):
        with self.assertRaises(ValidationError):
            StudentEnrollment.objects.create(
                student=self.student, class_stream=self.cs_a,
                start_date=date(2026, 5, 1), end_date=date(2026, 4, 1),
            )

    def test_overlapping_windows_rejected(self):
        StudentEnrollment.objects.create(
            student=self.student, class_stream=self.cs_a,
            start_date=date(2026, 1, 1), end_date=date(2026, 4, 1),
        )
        with self.assertRaises(ValidationError):
            StudentEnrollment.objects.create(
                student=self.student, class_stream=self.cs_a,
                start_date=date(2026, 3, 1), end_date=None,
            )

    def test_adjacent_half_open_windows_allowed(self):
        StudentEnrollment.objects.create(
            student=self.student, class_stream=self.cs_a,
            start_date=date(2026, 1, 1), end_date=date(2026, 4, 1),
        )
        second = StudentEnrollment.objects.create(
            student=self.student, class_stream=self.cs_a,
            start_date=date(2026, 4, 1), end_date=None,
)
        self.assertEqual(self.student.enrollments.count(), 2)
        self.assertTrue(second.is_current)

    def test_db_rejects_second_open_window(self):
        with self.assertRaises(IntegrityError):
            StudentEnrollment.objects.bulk_create([
                StudentEnrollment(
                    student=self.student, class_stream=self.cs_a,
                    start_date=date(2026, 1, 1), end_date=None,
                ),
                StudentEnrollment(
                    student=self.student, class_stream=self.cs_a,
                    start_date=date(2026, 3, 1), end_date=None,
                ),
            ])
        self.assertEqual(self.student.enrollments.count(), 0)

    def test_student_deletion_blocked_by_enrollment(self):
        StudentEnrollment.objects.create(
            student=self.student, class_stream=self.cs_a,
            start_date=self.student.date_admitted, end_date=None,
        )
        with self.assertRaises(ProtectedError):
            self.student.delete()

    def test_enrollment_created_by_and_current_flag(self):
        enrollment = StudentEnrollment.objects.create(
            student=self.student, class_stream=self.cs_a,
            start_date=self.student.date_admitted, end_date=None,
            created_by=self.admin,
        )
        self.assertTrue(enrollment.is_current)
        self.assertEqual(enrollment.created_by, self.admin)
        self.assertEqual(enrollment.reason, EnrollmentReason.ADMISSION)


class EnrollmentServiceTests(StudentAccessBase):
    def setUp(self):
        super().setUp()
        self.term = Term.objects.create(
            name='Term 1',
            year=AcademicYear.objects.create(
                name='2026', start_date='2026-01-01', end_date='2026-12-31',
            ),
            start_date='2026-01-10', end_date='2026-04-10',
        )

    def test_legacy_fallback_matches_current_class_without_history(self):
        self.assertTrue(
            student_in_class(self.student_a, self.cs_a.id, when=date(2026, 2, 1))
        )
        self.assertFalse(
            student_in_class(self.student_a, self.cs_b.id, when=date(2026, 2, 1))
        )

    def test_enrollment_drives_membership_after_history_exists(self):
        StudentEnrollment.objects.create(
            student=self.student_a, class_stream=self.cs_a,
            start_date=self.student_a.date_admitted, end_date=None,
        )
        self.assertTrue(
            student_in_class(self.student_a, self.cs_a.id, when=date(2026, 2, 1))
        )
        self.assertFalse(
            student_in_class(self.student_a, self.cs_b.id, when=date(2026, 2, 1))
        )

    def test_closed_window_ends_membership_at_exclusive_date(self):
        StudentEnrollment.objects.create(
            student=self.student_a, class_stream=self.cs_a,
            start_date=self.student_a.date_admitted, end_date=date(2026, 3, 1),
        )
        self.assertTrue(
            student_in_class(self.student_a, self.cs_a.id, when=date(2026, 2, 28))
        )
        self.assertFalse(
            student_in_class(self.student_a, self.cs_a.id, when=date(2026, 3, 1))
        )

    def test_get_class_roster_legacy_and_inactive_rule(self):
        roster = get_class_roster(self.cs_a)
        self.assertIn(self.student_a, roster)
        self.assertNotIn(self.student_b, roster)
        self.student_a.status = Student.Status.INACTIVE
        self.student_a.save(update_fields=['status'])
        self.assertNotIn(self.student_a, get_class_roster(self.cs_a))
        self.assertIn(self.student_a, get_class_roster(self.cs_a, include_inactive=True))

    def test_midterm_promotee_reported_in_both_term_rosters(self):
        StudentEnrollment.objects.create(
            student=self.student_a, class_stream=self.cs_a,
            start_date=self.student_a.date_admitted, end_date=None,
        )
        promote_student(
            actor=self.admin, student=self.student_a,
            target_class_stream=self.cs_b, effective_date=date(2026, 2, 20),
        )
        old_roster = get_class_roster_for_term(
            self.cs_a, self.term, include_inactive=True
        )
        new_roster = get_class_roster_for_term(
            self.cs_b, self.term, include_inactive=True
        )
        self.assertIn(self.student_a, old_roster)
        self.assertIn(self.student_a, new_roster)
        self.assertIn(self.student_b, new_roster)
        self.assertNotIn(self.student_b, old_roster)

    def test_daily_roster_follows_window_not_current_class(self):
        StudentEnrollment.objects.create(
            student=self.student_a, class_stream=self.cs_a,
            start_date=self.student_a.date_admitted, end_date=date(2026, 3, 1),
        )
        StudentEnrollment.objects.create(
            student=self.student_a, class_stream=self.cs_b,
            start_date=date(2026, 3, 1), end_date=None,
        )
        self.student_a.class_stream = self.cs_b
        self.student_a.save(update_fields=['class_stream'])
        pre = get_class_roster(self.cs_a, when=date(2026, 2, 15), include_inactive=True)
        post = get_class_roster(self.cs_a, when=date(2026, 3, 15), include_inactive=True)
        self.assertIn(self.student_a, pre)
        self.assertNotIn(self.student_a, post)
        self.assertIn(self.student_a, get_class_roster(
            self.cs_b, when=date(2026, 3, 15), include_inactive=True
        ))


class PromotionServiceTests(StudentAccessBase):
    def _admitted(self, adm, class_stream):
        student = Student.objects.create(
            admission_no=adm, first_name='Kim', last_name='Wanjala',
            gender='M', date_of_birth='2010-05-10', class_stream=class_stream,
            date_admitted='2026-01-10', status=Student.Status.ACTIVE,
        )
        record_admission(student, user=self.admin, start_date=student.date_admitted)
        return student

    def test_promote_student_splits_window_and_updates_class(self):
        student = self._admitted('2026/011', self.cs_a)
        promote_student(
            actor=self.admin, student=student,
            target_class_stream=self.cs_b, effective_date=date(2026, 3, 1),
            note='End of Form 2',
        )
        student.refresh_from_db()
        self.assertEqual(student.class_stream, self.cs_b)
        windows = list(student.enrollments.order_by('start_date'))
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].class_stream, self.cs_a)
        self.assertEqual(windows[0].end_date, date(2026, 3, 1))
        self.assertEqual(windows[0].reason, EnrollmentReason.ADMISSION)
        self.assertEqual(windows[1].class_stream, self.cs_b)
        self.assertEqual(windows[1].start_date, date(2026, 3, 1))
        self.assertIsNone(windows[1].end_date)
        self.assertEqual(windows[1].reason, EnrollmentReason.PROMOTION)
        self.assertEqual(windows[1].created_by, self.admin)

    def test_membership_before_and_after_promotion_date(self):
        student = self._admitted('2026/012', self.cs_a)
        promote_student(
            actor=self.admin, student=student,
            target_class_stream=self.cs_b, effective_date=date(2026, 3, 1),
        )
        self.assertTrue(student_in_class(student, self.cs_a.id, when=date(2026, 2, 15)))
        self.assertTrue(student_in_class(student, self.cs_b.id, when=date(2026, 3, 1)))
        self.assertFalse(student_in_class(student, self.cs_a.id, when=date(2026, 3, 1)))

    def test_validate_rejects_inactive_student(self):
        student = self._admitted('2026/013', self.cs_a)
        student.status = Student.Status.INACTIVE
        student.save(update_fields=['status'])
        problems = validate_promotion(
            target_class_stream=self.cs_b, students=[student],
            effective_date=date(2026, 3, 1),
        )
        self.assertEqual(len(problems), 1)
        self.assertIn('active', problems[0][1].lower())

    def test_validate_rejects_already_in_target(self):
        student = self._admitted('2026/014', self.cs_a)
        problems = validate_promotion(
            target_class_stream=self.cs_a, students=[student],
            effective_date=date(2026, 3, 1),
        )
        self.assertEqual(len(problems), 1)
        self.assertIn('target', problems[0][1].lower())

    def test_validate_rejects_effective_before_admission(self):
        student = self._admitted('2026/015', self.cs_a)
        problems = validate_promotion(
            target_class_stream=self.cs_b, students=[student],
            effective_date=date(2026, 1, 1),
        )
        self.assertEqual(len(problems), 1)
        self.assertIn('admission', problems[0][1].lower())

    def test_promote_rejects_when_no_window_covers_effective_date(self):
        student = Student.objects.create(
            admission_no='2026/016', first_name='Kim', last_name='Wanjala',
            gender='M', date_of_birth='2010-05-10', class_stream=self.cs_a,
            date_admitted='2026-01-10', status=Student.Status.ACTIVE,
        )
        with self.assertRaises(ValidationError):
            promote_student(
                actor=self.admin, student=student,
                target_class_stream=self.cs_b, effective_date=date(2026, 3, 1),
            )

    def test_batch_promotion_is_all_or_nothing(self):
        good = self._admitted('2026/017', self.cs_a)
        bad = self._admitted('2026/018', self.cs_a)
        bad.class_stream = self.cs_b
        bad.save(update_fields=['class_stream'])
        with self.assertRaises(ValidationError):
            promote_students(
                actor=self.admin, students=[good, bad],
                target_class_stream=self.cs_b, effective_date=date(2026, 3, 1),
            )
        good.refresh_from_db()
        self.assertEqual(good.class_stream, self.cs_a)
        self.assertEqual(good.enrollments.count(), 1)
        self.assertEqual(bad.enrollments.count(), 1)

    def test_batch_promotion_succeeds_for_all(self):
        s1 = self._admitted('2026/019', self.cs_a)
        s2 = self._admitted('2026/020', self.cs_a)
        created = promote_students(
            actor=self.admin, students=[s1, s2],
            target_class_stream=self.cs_b, effective_date=date(2026, 3, 1),
        )
        self.assertEqual(len(created), 2)
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertEqual(s1.class_stream, self.cs_b)
        self.assertEqual(s2.class_stream, self.cs_b)

    def test_correct_enrollment_rejects_end_before_start(self):
        student = self._admitted('2026/021', self.cs_a)
        window = student.enrollments.get()
        with self.assertRaises(ValidationError):
            correct_enrollment(
                actor=self.admin, enrollment=window, end_date=date(2025, 1, 1),
            )

    def test_correct_enrollment_closes_window(self):
        student = self._admitted('2026/022', self.cs_a)
        window = student.enrollments.get()
        correct_enrollment(
            actor=self.admin, enrollment=window, end_date=date(2026, 3, 1),
            note='Left school',
        )
        window.refresh_from_db()
        self.assertEqual(window.end_date, date(2026, 3, 1))
        self.assertEqual(window.note, 'Left school')
        self.assertEqual(window.created_by, self.admin)

    def test_record_class_change_splits_windows(self):
        student = self._admitted('2026/023', self.cs_a)
        record_class_change(student, self.cs_b, user=self.admin, when=date(2026, 6, 1))
        student.refresh_from_db()
        self.assertEqual(student.class_stream, self.cs_b)
        windows = list(student.enrollments.order_by('start_date'))
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].class_stream, self.cs_a)
        self.assertEqual(windows[0].end_date, date(2026, 6, 1))
        self.assertEqual(windows[1].class_stream, self.cs_b)
        self.assertEqual(windows[1].reason, EnrollmentReason.REASSIGNMENT)

    def test_record_class_change_splits_for_same_class_guard_is_caller_side(self):
        student = self._admitted('2026/024', self.cs_a)
        result = record_class_change(
            student, self.cs_a, user=self.admin, when=date(2026, 6, 1),
        )
        self.assertIsNotNone(result)
        student.refresh_from_db()
        self.assertEqual(student.class_stream, self.cs_a)
        self.assertEqual(student.enrollments.count(), 2)


class AdmissionAndEditWiringTests(StudentAccessBase):
    def test_student_create_records_admission_enrollment(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('students:add'), self._student_data()
        )
        self.assertEqual(response.status_code, 302)
        student = Student.objects.get(admission_no='2026/009')
        enrollment = student.enrollments.get()
        self.assertEqual(enrollment.class_stream, student.class_stream)
        self.assertEqual(enrollment.start_date, student.date_admitted)
        self.assertIsNone(enrollment.end_date)
        self.assertEqual(enrollment.reason, EnrollmentReason.ADMISSION)
        self.assertEqual(enrollment.created_by, self.admin)

    def test_class_change_on_edit_records_reassignment(self):
        self.client.force_login(self.admin)
        record_admission(self.student_a, user=self.admin)
        data = self._student_data(
            adm=self.student_a.admission_no, cs=self.cs_b,
        )
        response = self.client.post(
            reverse('students:edit', args=[self.student_a.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.student_a.refresh_from_db()
        self.assertEqual(self.student_a.class_stream, self.cs_b)
        windows = list(self.student_a.enrollments.order_by('start_date'))
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0].class_stream, self.cs_a)
        self.assertEqual(windows[1].class_stream, self.cs_b)
        self.assertEqual(windows[1].reason, EnrollmentReason.REASSIGNMENT)

    def test_edit_without_class_change_keeps_single_window(self):
        self.client.force_login(self.admin)
        record_admission(self.student_a, user=self.admin)
        data = self._student_data(
            adm=self.student_a.admission_no, cs=self.student_a.class_stream,
        )
        response = self.client.post(
            reverse('students:edit', args=[self.student_a.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.student_a.enrollments.count(), 1)


class PromotionViewTests(StudentAccessBase):
    def _admitted(self, adm, class_stream):
        student = Student.objects.create(
            admission_no=adm, first_name='Kim', last_name='Wanjala',
            gender='M', date_of_birth='2010-05-10', class_stream=class_stream,
            date_admitted='2026-01-10', status=Student.Status.ACTIVE,
        )
        record_admission(student, user=self.admin, start_date=student.date_admitted)
        return student

    def test_anonymous_redirected(self):
        response = self.client.get(reverse('students:promote'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.headers['Location'])

    def test_non_admin_rejected(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse('students:promote')).status_code, 403)
        self.assertEqual(self.client.post(reverse('students:promote')).status_code, 403)

    def test_admin_renders_promote_page(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('students:promote'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Promote Students')
        self.assertContains(response, self.student_a.admission_no)

    def test_admin_promotes_selected_students_on_post(self):
        self.client.force_login(self.admin)
        student = self._admitted('2026/025', self.cs_a)
        response = self.client.post(reverse('students:promote'), {
            'target_class_stream': self.cs_b.pk,
            'effective_date': '2026-03-01',
            'reason': 'PROMOTION',
            'note': 'End of Form 2',
            'students': [student.pk],
        })
        self.assertEqual(response.status_code, 302)
        student.refresh_from_db()
        self.assertEqual(student.class_stream, self.cs_b)
        self.assertEqual(student.enrollments.count(), 2)

    def test_admin_post_with_invalid_batch_changes_nothing(self):
        self.client.force_login(self.admin)
        student = self._admitted('2026/026', self.cs_a)
        response = self.client.post(reverse('students:promote'), {
            'target_class_stream': self.cs_b.pk,
            'effective_date': '2026-03-01',
            'reason': 'PROMOTION',
            'note': '',
            'students': [student.pk, self.student_b.pk],
        })
        self.assertEqual(response.status_code, 200)
        student.refresh_from_db()
        self.assertEqual(student.class_stream, self.cs_a)
        self.assertEqual(student.enrollments.count(), 1)
        self.student_b.refresh_from_db()
        self.assertEqual(self.student_b.class_stream, self.cs_b)

    def test_admin_post_prepended_class_filter(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('students:promote') + f'?class_stream={self.cs_a.pk}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.student_a.admission_no)
        self.assertNotContains(response, self.student_b.admission_no)


class EnrollmentBackfillMigrationTests(TestCase):
    def setUp(self):
        klass = SchoolClass.objects.create(name='Form 2')
        stream = Stream.objects.create(name='A')
        self.cs_a = ClassStream.objects.create(
            school_class=klass, stream=stream
        )
        self.cs_b = ClassStream.objects.create(
            school_class=SchoolClass.objects.create(name='Form 3'),
            stream=stream,
        )
        self.legacy = Student.objects.create(
            admission_no='2026/001', first_name='A', last_name='B',
            gender='M', date_of_birth='2010-01-01', class_stream=self.cs_a,
            date_admitted='2026-01-05', status=Student.Status.ACTIVE,
        )
        self.promoted = Student.objects.create(
            admission_no='2026/002', first_name='C', last_name='D',
            gender='M', date_of_birth='2010-01-01', class_stream=self.cs_a,
            date_admitted='2026-01-05', status=Student.Status.ACTIVE,
        )
        record_admission(self.promoted, start_date=self.promoted.date_admitted)

    def _migration(self):
        return importlib.import_module(
            'students.migrations.0004_backfill_student_enrollments'
        )

    def test_backfill_only_fills_legacy_students_and_is_reversible(self):
        migration = self._migration()
        migration.backfill(apps=global_apps, schema_editor=None)
        legacy_window = self.legacy.enrollments.get()
        self.assertEqual(legacy_window.class_stream, self.cs_a)
        self.assertEqual(
            legacy_window.start_date.isoformat(), self.legacy.date_admitted
        )
        self.assertIsNone(legacy_window.end_date)
        self.assertEqual(legacy_window.reason, EnrollmentReason.ADMISSION)
        self.assertEqual(self.promoted.enrollments.count(), 1)

        migration.backfill(apps=global_apps, schema_editor=None)
        self.assertEqual(self.legacy.enrollments.count(), 1)
        migration.reverse_backfill(apps=global_apps, schema_editor=None)
        self.assertEqual(self.legacy.enrollments.count(), 0)
        self.assertEqual(self.promoted.enrollments.count(), 1)
