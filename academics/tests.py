from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from academics.models import Assessment, GradeBand, Mark
from academics.services import assessment_results, save_mark, student_term_results
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
from students.models import Parent, Student, StudentParent
from students.services import promote_student, record_admission


class AcademicsAccessBase(TestCase):
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
        self.bio = Subject.objects.create(name='Biology', code='BIO')
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

        self.assessment = Assessment.objects.create(
            name='CAT 1', term=self.term, class_stream=self.cs_2a,
            subject=self.math, max_marks=100,
        )

        GradeBand.objects.create(
            label='A', min_percent='70', max_percent='100', points=12, comment='Excellent'
        )
        GradeBand.objects.create(
            label='B', min_percent='50', max_percent='69.99', points=10, comment='Good'
        )

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

    def _mark_payload(self, scores, status='ACTIVE'):
        students = Student.objects.filter(
            class_stream=self.cs_2a, status=status
        ).order_by('admission_no')
        payload = {
            'form-TOTAL_FORMS': str(students.count()),
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        for index, student in enumerate(students):
            payload[f'form-{index}-student'] = student.pk
            payload[f'form-{index}-scored'] = scores.get(student.pk, '')
        return payload

    def _login(self, user):
        self.client.force_login(user)


class AcademicPeriodTests(AcademicsAccessBase):
    def test_admin_can_create_academic_year(self):
        self._login(self.admin)
        response = self.client.post(reverse('academics:year_add'), {
            'name': '2027',
            'start_date': '2027-01-01',
            'end_date': '2027-12-31',
            'is_current': '',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AcademicYear.objects.filter(name='2027').exists())

    def test_admin_can_create_term(self):
        self._login(self.admin)
        response = self.client.post(reverse('academics:term_add'), {
            'name': 'Term 2',
            'year': self.year.pk,
            'start_date': '2026-05-01',
            'end_date': '2026-08-01',
            'is_current': '',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Term.objects.filter(name='Term 2', year=self.year).exists())

    def test_only_one_current_academic_year(self):
        with self.assertRaises(IntegrityError):
            AcademicYear.objects.create(
                name='2027', start_date='2027-01-01', end_date='2027-12-31',
                is_current=True,
            )

    def test_only_one_current_term(self):
        with self.assertRaises(IntegrityError):
            Term.objects.create(
                name='Term 2', year=self.year, start_date='2026-05-01',
                end_date='2026-08-01', is_current=True,
            )

    def test_set_current_year_clears_others(self):
        year_b = AcademicYear.objects.create(
            name='2027', start_date='2027-01-01', end_date='2027-12-31'
        )
        self._login(self.admin)
        response = self.client.post(
            reverse('academics:year_set_current', args=[year_b.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AcademicYear.objects.filter(pk=year_b.pk, is_current=True).exists())
        self.assertFalse(AcademicYear.objects.filter(pk=self.year.pk, is_current=True).exists())

    def test_set_current_year_rejects_get(self):
        year_b = AcademicYear.objects.create(
            name='2027', start_date='2027-01-01', end_date='2027-12-31'
        )
        self._login(self.admin)
        response = self.client.get(
            reverse('academics:year_set_current', args=[year_b.pk])
        )
        self.assertEqual(response.status_code, 405)

    def test_set_current_term_rejects_get(self):
        term_b = Term.objects.create(
            name='Term 2', year=self.year, start_date='2026-05-01',
            end_date='2026-08-01',
        )
        self._login(self.admin)
        response = self.client.get(
            reverse('academics:term_set_current', args=[term_b.pk])
        )
        self.assertEqual(response.status_code, 405)


class AssessmentAdminTests(AcademicsAccessBase):
    def test_admin_can_create_assessment(self):
        self._login(self.admin)
        response = self.client.post(reverse('academics:assessment_add'), {
            'name': 'Mid-Term',
            'class_stream': self.cs_2a.pk,
            'subject': self.math.pk,
            'term': self.term.pk,
            'assessment_type': Assessment.AssessmentType.MID_TERM,
            'date': '2026-03-15',
            'max_marks': '60',
            'weighting_percent': '100',
            'status': Assessment.Status.DRAFT,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Assessment.objects.filter(name='Mid-Term', class_stream=self.cs_2a).exists()
        )

    def test_invalid_assessment_rejected(self):
        self._login(self.admin)
        response = self.client.post(reverse('academics:assessment_add'), {
            'name': 'Bad',
            'class_stream': self.cs_2a.pk,
            'subject': self.math.pk,
            'term': self.term.pk,
            'assessment_type': Assessment.AssessmentType.CAT,
            'max_marks': '0',
            'weighting_percent': '100',
            'status': Assessment.Status.DRAFT,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Maximum marks must be greater than zero.')

    def test_duplicate_assessment_rejected(self):
        self._login(self.admin)
        response = self.client.post(reverse('academics:assessment_add'), {
            'name': 'CAT 1',
            'class_stream': self.cs_2a.pk,
            'subject': self.math.pk,
            'term': self.term.pk,
            'assessment_type': Assessment.AssessmentType.CAT,
            'date': '',
            'max_marks': '100',
            'weighting_percent': '100',
            'status': Assessment.Status.DRAFT,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Assessment.objects.filter(
                name='CAT 1', class_stream=self.cs_2a, subject=self.math,
            ).count(),
            1,
        )

    def test_same_name_allowed_for_other_class(self):
        TeacherAssignment.objects.create(
            teacher=self.class_teacher, class_stream=self.cs_3a,
            subject=self.math,
        )
        self._login(self.admin)
        response = self.client.post(reverse('academics:assessment_add'), {
            'name': 'CAT 1',
            'class_stream': self.cs_3a.pk,
            'subject': self.math.pk,
            'term': self.term.pk,
            'assessment_type': Assessment.AssessmentType.CAT,
            'date': '',
            'max_marks': '100',
            'weighting_percent': '100',
            'status': Assessment.Status.DRAFT,
        })
        self.assertEqual(response.status_code, 302)

    def test_teacher_cannot_create_assessment(self):
        self._login(self.teacher_user)
        response = self.client.post(reverse('academics:assessment_add'), {
            'name': 'Sneaky',
            'class_stream': self.cs_2a.pk,
            'subject': self.math.pk,
            'term': self.term.pk,
            'assessment_type': Assessment.AssessmentType.CAT,
            'date': '',
            'max_marks': '100',
            'weighting_percent': '100',
            'status': Assessment.Status.DRAFT,
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Assessment.objects.filter(name='Sneaky').exists())

    def test_parent_cannot_create_assessment(self):
        self._login(self.parent_user)
        response = self.client.get(reverse('academics:assessment_add'))
        self.assertEqual(response.status_code, 403)

    def test_orphan_assessment_rejected_without_assignment(self):
        self._login(self.admin)
        response = self.client.post(reverse('academics:assessment_add'), {
            'name': 'Orphan CAT',
            'class_stream': self.cs_3a.pk,
            'subject': self.bio.pk,
            'term': self.term.pk,
            'assessment_type': Assessment.AssessmentType.CAT,
            'date': '',
            'max_marks': '100',
            'weighting_percent': '100',
            'status': Assessment.Status.DRAFT,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No teacher is assigned')
        self.assertFalse(Assessment.objects.filter(name='Orphan CAT').exists())

    def test_orphan_assessment_rejected_in_edit(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('academics:assessment_edit', args=[self.assessment.pk]),
            {
                'name': self.assessment.name,
                'class_stream': self.cs_2a.pk,
                'subject': self.bio.pk,
                'term': self.term.pk,
                'assessment_type': Assessment.AssessmentType.CAT,
                'date': '',
                'max_marks': '100',
                'weighting_percent': '100',
                'status': Assessment.Status.DRAFT,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No teacher is assigned')
        self.assessment.refresh_from_db()
        self.assertEqual(self.assessment.subject, self.math)


class TeacherAuthorizationTests(AcademicsAccessBase):
    def test_authorized_teacher_sees_own_assessment_only(self):
        bio_assessment = Assessment.objects.create(
            name='Bio CAT', term=self.term, class_stream=self.cs_2a,
            subject=self.bio,
        )
        self._login(self.teacher_user)
        response = self.client.get(reverse('academics:marks'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'CAT 1')
        self.assertNotContains(response, 'Bio CAT')

    def test_authorized_teacher_can_view_assessment_detail(self):
        self._login(self.teacher_user)
        response = self.client.get(
            reverse('academics:assessment_detail', args=[self.assessment.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_view_other_subject_assessment(self):
        bio_assessment = Assessment.objects.create(
            name='Bio CAT', term=self.term, class_stream=self.cs_2a,
            subject=self.bio,
        )
        self._login(self.teacher_user)
        response = self.client.get(
            reverse('academics:assessment_detail', args=[bio_assessment.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_view_other_class_assessment(self):
        other = Assessment.objects.create(
            name='3A CAT', term=self.term, class_stream=self.cs_3a,
            subject=self.math,
        )
        self._login(self.teacher_user)
        response = self.client.get(
            reverse('academics:assessment_detail', args=[other.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_class_teacher_without_assignment_cannot_enter_marks(self):
        self._login(self.ct_user)
        response = self.client.get(
            reverse('academics:mark_entry', args=[self.assessment.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_open_mark_entry(self):
        self._login(self.parent_user)
        response = self.client.get(
            reverse('academics:mark_entry', args=[self.assessment.pk])
        )
        self.assertEqual(response.status_code, 403)


class MarkEntryTests(AcademicsAccessBase):
    def test_authorized_teacher_can_enter_marks(self):
        self._login(self.teacher_user)
        payload = self._mark_payload({self.s1.pk: '67', self.s2.pk: '81'})
        response = self.client.post(
            reverse('academics:mark_entry', args=[self.assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.assessment.marks.count(), 2)
        self.assertEqual(
            Mark.objects.get(student=self.s1).scored, 67
        )

    def test_authorized_teacher_can_edit_marks(self):
        save_mark(self.s1, self.assessment, '60')
        self._login(self.teacher_user)
        payload = self._mark_payload({self.s1.pk: '75', self.s2.pk: '80'})
        response = self.client.post(
            reverse('academics:mark_entry', args=[self.assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Mark.objects.get(student=self.s1).scored, 75)
        self.assertEqual(Mark.objects.count(), 2)

    def test_teacher_cannot_enter_marks_for_other_subject(self):
        bio_assessment = Assessment.objects.create(
            name='Bio CAT', term=self.term, class_stream=self.cs_2a,
            subject=self.bio,
        )
        self._login(self.teacher_user)
        payload = self._mark_payload({self.s1.pk: '50', self.s2.pk: '60'})
        response = self.client.post(
            reverse('academics:mark_entry', args=[bio_assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Mark.objects.filter(assessment=bio_assessment).count(), 0)

    def test_teacher_cannot_enter_marks_for_other_class(self):
        other = Assessment.objects.create(
            name='3A CAT', term=self.term, class_stream=self.cs_3a,
            subject=self.math,
        )
        self._login(self.teacher_user)
        payload = {
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0', 'form-MAX_NUM_FORMS': '1000',
            'form-0-student': self.s3.pk, 'form-0-scored': '50',
        }
        response = self.client.post(
            reverse('academics:mark_entry', args=[other.pk]), payload
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Mark.objects.filter(assessment=other).count(), 0)

    def test_negative_mark_rejected(self):
        self._login(self.teacher_user)
        payload = self._mark_payload({self.s1.pk: '-5'})
        response = self.client.post(
            reverse('academics:mark_entry', args=[self.assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ensure this value is greater than or equal to 0')
        self.assertEqual(self.assessment.marks.count(), 0)

    def test_mark_above_max_rejected(self):
        self._login(self.teacher_user)
        payload = self._mark_payload({self.s1.pk: '150'})
        response = self.client.post(
            reverse('academics:mark_entry', args=[self.assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, 'less than or equal to 100.00.'
        )
        self.assertEqual(self.assessment.marks.count(), 0)

    def test_duplicate_student_assessment_mark_not_duplicated(self):
        save_mark(self.s1, self.assessment, '61')
        save_mark(self.s1, self.assessment, '62')
        self.assertEqual(Mark.objects.filter(student=self.s1).count(), 1)

    def test_database_rejects_duplicate_mark(self):
        Mark.objects.create(
            student=self.s1, assessment=self.assessment, subject=self.math, scored=60
        )
        with self.assertRaises(IntegrityError):
            Mark.objects.create(
                student=self.s1, assessment=self.assessment, subject=self.math, scored=70
            )

    def test_student_from_other_stream_rejected(self):
        with self.assertRaises(ValidationError):
            save_mark(self.s3, self.assessment, '50')
        self.assertEqual(self.assessment.marks.count(), 0)

    def test_save_mark_subject_mismatch_rejected(self):
        mark = Mark(
            student=self.s1, assessment=self.assessment, subject=self.bio, scored=50
        )
        with self.assertRaises(ValidationError):
            mark.full_clean()


class PublishedAssessmentLockTests(AcademicsAccessBase):
    def setUp(self):
        super().setUp()
        self.assessment.status = Assessment.Status.PUBLISHED
        self.assessment.save(update_fields=['status'])
        save_mark(self.s1, self.assessment, '50')

    def test_teacher_cannot_post_marks_on_published_assessment(self):
        self._login(self.teacher_user)
        payload = self._mark_payload({self.s1.pk: '99', self.s2.pk: '99'})
        response = self.client.post(
            reverse('academics:mark_entry', args=[self.assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Mark.objects.get(student=self.s1).scored, 50)
        self.assertFalse(
            Mark.objects.filter(student=self.s2, assessment=self.assessment).exists()
        )

    def test_teacher_redirected_from_mark_entry_get_for_published(self):
        self._login(self.teacher_user)
        response = self.client.get(
            reverse('academics:mark_entry', args=[self.assessment.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse('academics:assessment_detail', args=[self.assessment.pk]),
            response.url,
        )

    def test_admin_can_still_enter_marks_on_published_assessment(self):
        self._login(self.admin)
        payload = self._mark_payload({self.s1.pk: '88', self.s2.pk: '90'})
        response = self.client.post(
            reverse('academics:mark_entry', args=[self.assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Mark.objects.get(student=self.s1).scored, 88)


class ResultsAndGradingTests(AcademicsAccessBase):
    def test_assessment_results_average_and_grade(self):
        save_mark(self.s1, self.assessment, '67')
        save_mark(self.s2, self.assessment, '81')
        results = assessment_results(self.assessment)
        self.assertEqual(results['count'], 2)
        self.assertEqual(float(results['average']), 74.0)
        self.assertEqual(float(results['average_percent']), 74.0)
        labels = {row['grade'].label for row in results['rows']}
        self.assertEqual(labels, {'B', 'A'})

    def test_student_term_results_per_subject_and_overall(self):
        bio_assessment = Assessment.objects.create(
            name='Bio CAT', term=self.term, class_stream=self.cs_2a,
            subject=self.bio, status=Assessment.Status.PUBLISHED,
        )
        self.assessment.status = Assessment.Status.PUBLISHED
        self.assessment.save(update_fields=['status'])
        save_mark(self.s1, self.assessment, '80')
        save_mark(self.s1, bio_assessment, '40')
        results = student_term_results(self.s1, self.term)
        self.assertEqual(len(results['rows']), 2)
        self.assertEqual(float(results['totals']['scored']), 120.0)
        self.assertEqual(float(results['totals']['max']), 200.0)
        self.assertEqual(float(results['overall_percent']), 60.0)

    def test_draft_assessments_excluded_from_parent_results(self):
        save_mark(self.s1, self.assessment, '80')
        results = student_term_results(self.s1, self.term)
        self.assertEqual(results['rows'], [])
        self.assertEqual(float(results['overall_percent']), 0.0)


class ParentResultsTests(AcademicsAccessBase):
    def test_parent_can_view_own_child_results(self):
        self.assessment.status = Assessment.Status.PUBLISHED
        self.assessment.save(update_fields=['status'])
        save_mark(self.s1, self.assessment, '80')
        self._login(self.parent_user)
        response = self.client.get(
            reverse('academics:child_results', args=[self.s1.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')
        self.assertContains(response, '80')

    def test_parent_cannot_view_other_child_results(self):
        self._login(self.parent_user)
        response = self.client.get(
            reverse('academics:child_results', args=[self.s3.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_modify_marks(self):
        save_mark(self.s1, self.assessment, '55')
        self._login(self.parent_user)
        payload = self._mark_payload({self.s1.pk: '99'})
        response = self.client.post(
            reverse('academics:mark_entry', args=[self.assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Mark.objects.get(student=self.s1).scored, 55)

    def test_admin_can_view_any_child_results(self):
        other = Assessment.objects.create(
            name='3A CAT', term=self.term, class_stream=self.cs_3a,
            subject=self.math, status=Assessment.Status.PUBLISHED,
        )
        save_mark(self.s3, other, '70')
        self._login(self.admin)
        response = self.client.get(
            reverse('academics:child_results', args=[self.s3.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '70')


class HistoricalIntegrityTests(AcademicsAccessBase):
    def test_marks_remain_after_student_deactivated(self):
        save_mark(self.s1, self.assessment, '60')
        self.s1.status = Student.Status.TRANSFERRED
        self.s1.save(update_fields=['status'])
        results = assessment_results(self.assessment)
        self.assertEqual(results['count'], 1)
        self.assertEqual(results['rows'][0]['mark'].student, self.s1)

    def test_deactivated_student_excluded_from_new_entry(self):
        self.s1.status = Student.Status.INACTIVE
        self.s1.save(update_fields=['status'])
        self._login(self.teacher_user)
        payload = {
            'form-TOTAL_FORMS': '1', 'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0', 'form-MAX_NUM_FORMS': '1000',
            'form-0-student': self.s2.pk, 'form-0-scored': '70',
        }
        response = self.client.post(
            reverse('academics:mark_entry', args=[self.assessment.pk]), payload
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Mark.objects.filter(student=self.s1, assessment=self.assessment).exists()
        )

    def test_grade_band_overlap_rejected(self):
        with self.assertRaises(ValidationError):
            GradeBand(
                label='D', min_percent='60', max_percent='80', points=6
            ).full_clean()


class AnonymousAccessTests(AcademicsAccessBase):
    def test_anonymous_redirected_to_login(self):
        urls = [
            reverse('academics:home'),
            reverse('academics:year_list'),
            reverse('academics:assessment_list'),
            reverse('academics:marks'),
            reverse('academics:mark_entry', args=[self.assessment.pk]),
            reverse('academics:my_classes'),
            reverse('academics:performance'),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])


class UnlinkedTeacherTests(AcademicsAccessBase):
    def setUp(self):
        super().setUp()
        self.unlinked = self._make_user('ghostteacher', 'TEACHER')

    def test_my_classes_renders_empty_state_not_500(self):
        self._login(self.unlinked)
        response = self.client.get(reverse('academics:my_classes'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No teacher profile is linked to your account.')

    def test_marks_page_renders_empty_state_not_500(self):
        self._login(self.unlinked)
        response = self.client.get(reverse('academics:marks'))
        self.assertEqual(response.status_code, 200)

    def test_results_mixins_deny_unlinked_teacher(self):
        self._login(self.unlinked)
        response = self.client.get(
            reverse('academics:assessment_detail', args=[self.assessment.pk])
        )
        self.assertEqual(response.status_code, 403)


class MyClassesCoverageTests(AcademicsAccessBase):
    def test_class_teacher_sees_headed_stream(self):
        self._login(self.ct_user)
        response = self.client.get(reverse('academics:my_classes'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Form 2 A')
        self.assertContains(response, 'Class teacher')

    def test_whole_class_coverage_seen_by_teacher(self):
        self.teacher.classes.add(self.klass_3)
        self._login(self.teacher_user)
        response = self.client.get(reverse('academics:my_classes'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Form 3 A')
        self.assertContains(response, 'Whole-class coverage')

    def test_subject_teacher_sees_assignment_with_marks_link(self):
        self._login(self.teacher_user)
        response = self.client.get(reverse('academics:my_classes'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Form 2 A')
        self.assertContains(response, 'Mathematics')
        self.assertContains(response, 'Select Assessment')


class GradeBandUiTests(AcademicsAccessBase):
    def test_admin_can_create_grade_band(self):
        self._login(self.admin)
        response = self.client.post(reverse('academics:gradeband_add'), {
            'label': 'C',
            'min_percent': '40',
            'max_percent': '49.99',
            'points': '8',
            'comment': 'Average',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(GradeBand.objects.filter(label='C').exists())

    def test_admin_can_edit_and_delete_grade_band(self):
        self._login(self.admin)
        band = GradeBand.objects.get(label='A')
        response = self.client.post(
            reverse('academics:gradeband_edit', args=[band.pk]),
            {'label': 'A', 'min_percent': '75', 'max_percent': '100',
             'points': '12', 'comment': 'Excellent'},
        )
        self.assertEqual(response.status_code, 302)
        band.refresh_from_db()
        self.assertEqual(band.min_percent, 75)

        response = self.client.post(
            reverse('academics:gradeband_delete', args=[band.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(GradeBand.objects.filter(pk=band.pk).exists())

    def test_overlapping_band_rejected_in_ui(self):
        self._login(self.admin)
        response = self.client.post(reverse('academics:gradeband_add'), {
            'label': 'D',
            'min_percent': '60',
            'max_percent': '80',
            'points': '6',
            'comment': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'overlaps')
        self.assertFalse(GradeBand.objects.filter(label='D').exists())

    def test_list_is_admin_only(self):
        self._login(self.teacher_user)
        self.assertEqual(
            self.client.get(reverse('academics:gradeband_list')).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse('academics:gradeband_add')).status_code, 403
        )


class EnrollmentHistoricalMarkTests(AcademicsAccessBase):
    def setUp(self):
        super().setUp()
        record_admission(self.s1, start_date=self.s1.date_admitted)
        promote_student(
            actor=self.admin, student=self.s1,
            target_class_stream=self.cs_3a, effective_date=date(2026, 2, 20),
        )
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.class_stream, self.cs_3a)

    def _assessment_in(self, class_stream, date_value):
        return Assessment.objects.create(
            name=f'{class_stream} CAT', term=self.term,
            class_stream=class_stream, subject=self.math,
            date=date_value, max_marks=100,
        )

    def test_mark_valid_in_old_class_before_promotion(self):
        save_mark(self.s1, self._assessment_in(self.cs_2a, date(2026, 2, 10)), '60')
        self.assertEqual(self.s1.marks.count(), 1)

    def test_mark_valid_in_new_class_after_promotion(self):
        save_mark(self.s1, self._assessment_in(self.cs_3a, date(2026, 3, 10)), '70')
        self.assertEqual(self.s1.marks.count(), 1)

    def test_mark_rejected_in_old_class_after_promotion(self):
        late = self._assessment_in(self.cs_2a, date(2026, 3, 10))
        with self.assertRaises(ValidationError):
            save_mark(self.s1, late, '60')
        self.assertEqual(self.s1.marks.count(), 0)

    def test_mark_undefined_date_uses_term_start(self):
        save_mark(self.s1, self.assessment, '75')
        self.assertEqual(self.s1.marks.count(), 1)

    def test_mark_entry_roster_keeps_promoted_student_for_term(self):
        self._login(self.teacher_user)
        response = self.client.get(
            reverse('academics:mark_entry', args=[self.assessment.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')