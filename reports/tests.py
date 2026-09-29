from datetime import date

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from academics.models import Assessment, GradeBand, Mark
from academics.services import save_mark
from attendance.models import Attendance
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
from fees.models import FeePayment, StudentCharge, StudentFeeAccount
from students.models import Parent, Student, StudentParent
from students.services import promote_student, record_admission

from .services import (
    class_attendance_report,
    class_term_ranking,
    class_term_report,
    eligibility_data,
    membership_assessments,
    student_attendance_summary,
    student_report,
)


class ReportsBase(TestCase):
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
        self.chem = Subject.objects.create(name='Chemistry', code='CHE')
        self.phy = Subject.objects.create(name='Physics', code='PHY')
        self.dept = Department.objects.create(name='Science', code='SCI')

        self.admin = self._make_user('admin', 'ADMIN')

        self.teacher_user = self._make_user('teacher1', 'TEACHER')
        self.teacher = self._make_teacher(
            'T001', 'John', 'Kamau', user=self.teacher_user
        )
        TeacherAssignment.objects.create(
            teacher=self.teacher, class_stream=self.cs_2a, subject=self.math
        )

        self.ct_user = self._make_user('ct1', 'TEACHER')
        self.ct = self._make_teacher(
            'T002', 'Grace', 'Wanjiru', user=self.ct_user
        )
        self.cs_3a.class_teacher = self.ct
        self.cs_3a.save(update_fields=['class_teacher'])
        TeacherAssignment.objects.create(
            teacher=self.ct, class_stream=self.cs_2a, subject=self.math
        )

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
            subject=self.math, max_marks=100, status=Assessment.Status.PUBLISHED,
        )
        GradeBand.objects.create(
            label='A', min_percent='70', max_percent='100', points=12,
            comment='Excellent',
        )
        GradeBand.objects.create(
            label='B', min_percent='50', max_percent='69.99', points=10,
            comment='Good',
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

    def _login(self, user):
        self.client.force_login(user)

    def _assessment(self, name, class_stream, subject, date_value=None,
                    status=Assessment.Status.PUBLISHED):
        return Assessment.objects.create(
            name=name, term=self.term, class_stream=class_stream,
            subject=subject, date=date_value, max_marks=100, status=status,
        )


class RankingEligibilityTests(ReportsBase):
    def test_no_published_assessments_yields_no_ranking(self):
        self.assessment.status = Assessment.Status.DRAFT
        self.assessment.save(update_fields=['status'])
        self.assertEqual(class_term_ranking(self.cs_2a, self.term), [])

    def test_single_published_assessment_ranks_students_with_marks(self):
        save_mark(self.s1, self.assessment, '60')
        ranking = class_term_ranking(self.cs_2a, self.term)
        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0]['position'], 1)
        self.assertIsNotNone(ranking[0]['overall_grade'])

    def test_missing_marks_leave_student_unranked(self):
        self.assertEqual(class_term_ranking(self.cs_2a, self.term), [])

    def test_insufficient_assessment_coverage_not_ranked(self):
        math_b = self._assessment(
            'CAT 2', self.cs_2a, self.math, date(2026, 2, 10)
        )
        self._assessment('CBT 1', self.cs_2a, self.bio, date(2026, 3, 1))
        save_mark(self.s1, self.assessment, '60')
        save_mark(self.s1, math_b, '70')
        save_mark(self.s2, self.assessment, '80')
        ranking = class_term_ranking(self.cs_2a, self.term)
        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0]['student_id'], self.s1.pk)

        s1_assessments = membership_assessments(self.cs_2a, self.term, self.s1)
        eligible_s1, info = eligibility_data(self.s1, s1_assessments)
        self.assertTrue(eligible_s1)
        self.assertEqual(info['records_required'], 2)

        eligible_s2, info = eligibility_data(self.s2, s1_assessments)
        self.assertFalse(eligible_s2)
        self.assertEqual(info['records'], 1)

    def test_insufficient_subject_coverage_not_ranked(self):
        self.assessment.delete()
        a_math = self._assessment(
            'Math A', self.cs_2a, self.math, date(2026, 2, 1)
        )
        math_b = self._assessment(
            'Math B', self.cs_2a, self.math, date(2026, 2, 2)
        )
        a_bio = self._assessment(
            'Bio A', self.cs_2a, self.bio, date(2026, 2, 3)
        )
        a_chem = self._assessment(
            'Chem A', self.cs_2a, self.chem, date(2026, 2, 4)
        )
        assessments = list(membership_assessments(self.cs_2a, self.term, self.s1))
        self.assertEqual(len(assessments), 4)

        save_mark(self.s1, a_math, '60')
        save_mark(self.s1, math_b, '70')
        eligible_s1, info = eligibility_data(self.s1, assessments)
        self.assertFalse(eligible_s1)
        self.assertEqual(info['records_required'], 2)
        self.assertEqual(info['subjects'], 1)
        self.assertEqual(info['subjects_required'], 2)

        save_mark(self.s2, a_math, '80')
        save_mark(self.s2, a_bio, '90')
        eligible_s2, info = eligibility_data(self.s2, assessments)
        self.assertTrue(eligible_s2)
        self.assertEqual(info['subjects'], 2)


class RankingRuleTests(ReportsBase):
    def test_standard_competition_ranking_with_ties(self):
        s4 = Student.objects.create(
            admission_no='2026/004', first_name='Ann', last_name='Njeri',
            gender='F', date_of_birth='2011-03-01', class_stream=self.cs_2a,
            date_admitted='2026-01-05', status=Student.Status.ACTIVE,
        )
        save_mark(self.s1, self.assessment, '80')
        save_mark(self.s2, self.assessment, '80')
        save_mark(s4, self.assessment, '60')
        ranking = class_term_ranking(self.cs_2a, self.term)
        self.assertEqual([r['student_id'] for r in ranking],
                         [self.s1.pk, self.s2.pk, s4.pk])
        self.assertEqual([r['position'] for r in ranking], [1, 1, 3])
        self.assertEqual(ranking[0]['admission_no'], '2026/001')
        self.assertEqual(len(ranking), 3)

    def test_ranking_scoped_to_class(self):
        other = Assessment.objects.create(
            name='3A CAT', term=self.term, class_stream=self.cs_3a,
            subject=self.math, max_marks=100,
            status=Assessment.Status.PUBLISHED,
        )
        save_mark(self.s1, self.assessment, '60')
        save_mark(self.s3, other, '60')
        self.assertEqual(len(class_term_ranking(self.cs_2a, self.term)), 1)
        self.assertEqual(len(class_term_ranking(self.cs_3a, self.term)), 1)

    def test_rank_key_is_class_scoped_overall_percent(self):
        math_b = self._assessment(
            'CAT 2', self.cs_2a, self.math, date(2026, 2, 10)
        )
        save_mark(self.s1, self.assessment, '80')
        save_mark(self.s1, math_b, '50')
        save_mark(self.s2, self.assessment, '70')
        ranking = class_term_ranking(self.cs_2a, self.term)
        by_id = {r['student_id']: r for r in ranking}
        self.assertEqual(float(by_id[self.s1.pk]['overall_percent']), 65.0)
        self.assertEqual(by_id[self.s1.pk]['position'], 2)


class ClassTermReportTests(ReportsBase):
    def test_report_flags_students_without_marks(self):
        save_mark(self.s1, self.assessment, '60')
        report = class_term_report(self.cs_2a, self.term)
        self.assertEqual(report['summary']['roster_count'], 2)
        self.assertEqual(report['summary']['ranked_count'], 1)
        by_student = {row['student'].pk: row for row in report['rows']}
        self.assertIsNone(by_student[self.s2.pk]['position'])
        self.assertFalse(by_student[self.s2.pk]['eligible'])
        self.assertEqual(float(report['summary']['average_percent']), 60.0)

    def test_inactive_student_flagged_and_ranked(self):
        save_mark(self.s1, self.assessment, '60')
        self.s2.status = Student.Status.TRANSFERRED
        self.s2.save(update_fields=['status'])
        report = class_term_report(self.cs_2a, self.term)
        by_student = {row['student'].pk: row for row in report['rows']}
        self.assertTrue(by_student[self.s2.pk]['is_inactive'])
        self.assertEqual(len(report['rows']), 2)

    def test_subject_averages_over_students_with_marks(self):
        bio_assessment = self._assessment(
            'Bio CAT', self.cs_2a, self.bio, date(2026, 2, 1)
        )
        save_mark(self.s1, self.assessment, '80')
        save_mark(self.s1, bio_assessment, '40')
        report = class_term_report(self.cs_2a, self.term)
        by_subject = {row['subject'].name: row for row in report['subject_averages']}
        self.assertEqual(float(by_subject['Biology']['average_percent']), 40.0)
        self.assertEqual(by_subject['Biology']['students_with_marks'], 1)
        self.assertEqual(by_subject['Biology']['no_mark_count'], 1)


class PublishedOnlyTests(ReportsBase):
    def test_draft_assessments_excluded_from_ranking_and_report(self):
        draft = self._assessment(
            'DRAFT CAT', self.cs_2a, self.math, date(2026, 2, 5),
            status=Assessment.Status.DRAFT,
        )
        save_mark(self.s1, self.assessment, '60')
        save_mark(self.s1, draft, '100')
        ranking = class_term_ranking(self.cs_2a, self.term)
        self.assertEqual(float(ranking[0]['overall_percent']), 60.0)
        self.assertEqual(len(membership_assessments(self.cs_2a, self.term, self.s1)), 1)

        report = class_term_report(self.cs_2a, self.term)
        by_student = {row['student'].pk: row for row in report['rows']}
        self.assertEqual(by_student[self.s1.pk]['records'], 1)
        self.assertEqual(by_student[self.s1.pk]['total'], 1)


class HistoricalMembershipTests(ReportsBase):
    def setUp(self):
        super().setUp()
        record_admission(self.s1, start_date='2026-01-05')
        promote_student(
            actor=self.admin, student=self.s1,
            target_class_stream=self.cs_3a, effective_date=date(2026, 2, 20),
        )
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.class_stream, self.cs_3a)

    def test_student_ranked_in_both_classes_for_term(self):
        early = self._assessment('2A Early', self.cs_2a, self.math, date(2026, 1, 25))
        late = self._assessment('3A Late', self.cs_3a, self.math, date(2026, 3, 5))
        save_mark(self.s1, early, '80')
        save_mark(self.s3, late, '70')
        save_mark(self.s1, late, '90')

        rank_2a = class_term_ranking(self.cs_2a, self.term)
        self.assertEqual(len(rank_2a), 1)
        self.assertEqual(float(rank_2a[0]['overall_percent']), 80.0)

        rank_3a = class_term_ranking(self.cs_3a, self.term)
        self.assertEqual(len(rank_3a), 2)

        report = student_report(self.term, self.s1)
        class_names = {r['class_stream'].pk for r in report['ranks']}
        self.assertEqual(class_names, {self.cs_2a.pk, self.cs_3a.pk})

    def test_window_restricts_old_class_assessments(self):
        self.assessment.delete()
        early = self._assessment(
            '2A Early', self.cs_2a, self.math, date(2026, 1, 25)
        )
        self._assessment('2A Late', self.cs_2a, self.math, date(2026, 2, 25))
        window_assessments = membership_assessments(self.cs_2a, self.term, self.s1)
        self.assertEqual(window_assessments, [early])

    def test_student_report_rank_in_new_class(self):
        late = self._assessment('3A Late', self.cs_3a, self.math, date(2026, 3, 5))
        save_mark(self.s1, late, '90')
        report = student_report(self.term, self.s1)
        for rank in report['ranks']:
            if rank['class_stream'].pk == self.cs_3a.pk:
                self.assertEqual(rank['position'], 1)


class ClassPerformanceViewTests(ReportsBase):
    def _url(self, extra=''):
        return reverse('reports:class_performance') + extra

    def test_admin_can_view_class_performance(self):
        save_mark(self.s1, self.assessment, '60')
        self._login(self.admin)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')
        self.assertContains(response, '60.0')

    def test_teacher_can_view_own_scope(self):
        save_mark(self.s1, self.assessment, '60')
        self._login(self.teacher_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')

    def test_teacher_probe_out_of_scope_class_denied(self):
        self._login(self.teacher_user)
        response = self.client.get(
            self._url(f'?term={self.term.pk}&class_stream={self.cs_3a.pk}')
        )
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_view_class_performance(self):
        self._login(self.parent_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.headers['Location'])

    def test_unlinked_teacher_sees_empty_state(self):
        ghost = self._make_user('ghostteacher', 'TEACHER')
        self._make_teacher('T999', 'Ghost', 'Teacher', user=ghost)
        self._login(ghost)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a term and a class stream')

    def test_class_performance_csv(self):
        save_mark(self.s1, self.assessment, '60')
        self._login(self.admin)
        response = self.client.get(
            reverse('reports:class_performance_csv')
            + f'?term={self.term.pk}&class_stream={self.cs_2a.pk}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        body = response.content.decode()
        self.assertIn('2026/001', body)
        self.assertIn('60.00', body)

    def test_class_performance_csv_denied_out_of_scope(self):
        self._login(self.teacher_user)
        response = self.client.get(
            reverse('reports:class_performance_csv')
            + f'?class_stream={self.cs_3a.pk}'
        )
        self.assertEqual(response.status_code, 403)


class StudentReportViewTests(ReportsBase):
    def setUp(self):
        super().setUp()
        save_mark(self.s1, self.assessment, '60')
        save_mark(self.s2, self.assessment, '80')

    def _url(self, pk):
        return reverse('reports:student_report', args=[pk])

    def test_parent_can_view_own_child_report(self):
        self._login(self.parent_user)
        response = self.client.get(self._url(self.s1.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')

    def test_parent_cannot_view_other_child_report(self):
        self._login(self.parent_user)
        response = self.client.get(self._url(self.s3.pk))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_view_any_student_report(self):
        self._login(self.admin)
        response = self.client.get(self._url(self.s3.pk))
        self.assertEqual(response.status_code, 200)

    def test_teacher_can_view_student_in_scope(self):
        self._login(self.teacher_user)
        response = self.client.get(self._url(self.s1.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')

    def test_teacher_cannot_view_student_out_of_scope(self):
        self._login(self.teacher_user)
        response = self.client.get(self._url(self.s3.pk))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self._url(self.s1.pk))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.headers['Location'])

    def test_report_card_csv_scoped_to_parent(self):
        self._login(self.parent_user)
        response = self.client.get(
            reverse('reports:student_report_csv', args=[self.s1.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        self.assertIn('OVERALL', response.content.decode())

        response = self.client.get(
            reverse('reports:student_report_csv', args=[self.s3.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_report_card_csv_denied_for_teacher_out_of_scope(self):
        self._login(self.teacher_user)
        response = self.client.get(
            reverse('reports:student_report_csv', args=[self.s3.pk])
        )
        self.assertEqual(response.status_code, 403)


class AttendanceReportTests(ReportsBase):
    def setUp(self):
        super().setUp()
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a,
            date=date(2026, 1, 20), status=Attendance.Status.PRESENT,
        )
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a,
            date=date(2026, 1, 21), status=Attendance.Status.ABSENT,
        )
        Attendance.objects.create(
            student=self.s2, class_stream=self.cs_2a,
            date=date(2026, 1, 20), status=Attendance.Status.LATE,
        )
        Attendance.objects.create(
            student=self.s3, class_stream=self.cs_3a,
            date=date(2026, 1, 20), status=Attendance.Status.PRESENT,
        )

    def _url(self):
        return reverse('reports:attendance')

    def test_admin_sees_class_attendance_report(self):
        self._login(self.admin)
        response = self.client.get(
            self._url() + f'?class_stream={self.cs_2a.pk}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')
        self.assertContains(response, '50.0')
        self.assertContains(response, 'Mary Wanjiku')

    def test_class_teacher_sees_own_stream(self):
        self._login(self.ct_user)
        response = self.client.get(
            self._url() + f'?class_stream={self.cs_3a.pk}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Peter Otieno')

    def test_non_attendance_teacher_gets_empty_state_not_403(self):
        self._login(self.teacher_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select a term and a class stream')

    def test_teacher_probe_out_of_scope_class_denied(self):
        self._login(self.teacher_user)
        response = self.client.get(
            self._url() + f'?class_stream={self.cs_3a.pk}'
        )
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_view_attendance_report(self):
        self._login(self.parent_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)

    def test_attendance_csv_includes_percentages(self):
        self._login(self.admin)
        response = self.client.get(
            reverse('reports:attendance_csv')
            + f'?class_stream={self.cs_2a.pk}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        body = response.content.decode()
        self.assertIn('2026/001', body)
        self.assertIn('50.00', body)

    def test_student_attendance_summary_counts(self):
        summary = student_attendance_summary(self.s1, self.term)
        self.assertEqual(summary['present'], 1)
        self.assertEqual(summary['absent'], 1)
        self.assertEqual(summary['recorded_days'], 2)
        self.assertEqual(float(summary['percent']), 50.0)

    def test_class_attendance_report_daily_rollup(self):
        report = class_attendance_report(self.cs_2a, self.term)
        self.assertEqual(report['days_with_records'], 2)
        by_day = {row['date']: row for row in report['daily']}
        self.assertEqual(by_day[date(2026, 1, 20)]['PRESENT'], 1)
        self.assertEqual(by_day[date(2026, 1, 20)]['LATE'], 1)


class ParentAttendanceViewTests(ReportsBase):
    def setUp(self):
        super().setUp()
        Attendance.objects.create(
            student=self.s1, class_stream=self.cs_2a,
            date=date(2026, 1, 20), status=Attendance.Status.PRESENT,
        )

    def test_parent_sees_own_children_summary(self):
        self._login(self.parent_user)
        response = self.client.get(reverse('reports:attendance_my_children'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')
        self.assertContains(response, '100.0')

    def test_parent_sees_child_detail(self):
        self._login(self.parent_user)
        response = self.client.get(
            reverse('reports:attendance_child', args=[self.s1.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')

    def test_parent_cannot_view_other_child_detail(self):
        self._login(self.parent_user)
        response = self.client.get(
            reverse('reports:attendance_child', args=[self.s3.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        for url in [
            reverse('reports:attendance_my_children'),
            reverse('reports:attendance_child', args=[self.s1.pk]),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])


class FinanceReportTests(ReportsBase):
    def setUp(self):
        super().setUp()
        account = StudentFeeAccount.objects.create(
            student=self.s1, term=self.term
        )
        StudentCharge.objects.create(
            student=self.s1, term=self.term, description='Tuition',
            amount='20000.00', created_by=self.admin,
        )
        FeePayment.objects.create(
            account=account, amount='5000.00', method='CASH',
            recorded_by=self.admin,
        )

    def _url(self):
        return reverse('reports:finance')

    def test_admin_sees_finance_report(self):
        self._login(self.admin)
        response = self.client.get(
            self._url() + f'?class_stream={self.cs_2a.pk}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')
        self.assertContains(response, '20000.00')
        self.assertContains(response, '5000.00')
        self.assertContains(response, '15000.00')

    def test_teacher_cannot_view_finance_report(self):
        self._login(self.ct_user)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 403)

    def test_finance_csv_admin_only(self):
        self._login(self.admin)
        response = self.client.get(
            reverse('reports:finance_csv')
            + f'?class_stream={self.cs_2a.pk}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/csv', response['Content-Type'])
        self.assertIn('15000.00', response.content.decode())


class ReportsHomeTests(ReportsBase):
    def test_reports_home_admin_only(self):
        self._login(self.admin)
        response = self.client.get(reverse('reports:home'))
        self.assertEqual(response.status_code, 200)

        self._login(self.teacher_user)
        self.assertEqual(
            self.client.get(reverse('reports:home')).status_code, 403
        )
        self._login(self.parent_user)
        self.assertEqual(
            self.client.get(reverse('reports:home')).status_code, 403
        )

    def test_reports_home_anonymous_redirect(self):
        response = self.client.get(reverse('reports:home'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.headers['Location'])


class MigrationCleanlinessTests(ReportsBase):
    def test_reports_requires_no_migrations(self):
        call_command('makemigrations', 'reports', '--check', '--dry-run')