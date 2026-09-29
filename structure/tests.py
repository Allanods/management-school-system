from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import (
    ClassStream,
    SchoolClass,
    Stream,
    Subject,
    Teacher,
    TeacherAssignment,
)
from students.models import Student


class StructureAccessBase(TestCase):
    def setUp(self):
        self.klass = SchoolClass.objects.create(name='Form 2')
        self.stream_a = Stream.objects.create(name='A')
        self.cs_a = ClassStream.objects.create(
            school_class=self.klass, stream=self.stream_a
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
        self.assignment = TeacherAssignment.objects.create(
            teacher=self.teacher, class_stream=self.cs_a, subject=self.subject
        )

        self.parent_user = self._make_user('parent1', 'PARENT')

    def _make_user(self, username, role):
        user = User.objects.create_user(username)
        user.profile.role = role
        user.profile.save()
        return user

    def _make_student(self, adm='2026/001', cs=None):
        return Student.objects.create(
            admission_no=adm,
            first_name='Brian',
            last_name='Otieno',
            gender='M',
            date_of_birth='2010-05-10',
            class_stream=cs or self.cs_a,
            date_admitted='2026-01-10',
        )


class ClassAdminTests(StructureAccessBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_admin_can_create_class(self):
        response = self.client.post(
            reverse('structure:class_add'),
            {'name': 'Form 3', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(SchoolClass.objects.filter(name='Form 3').exists())

    def test_duplicate_class_rejected(self):
        response = self.client.post(
            reverse('structure:class_add'),
            {'name': 'Form 2', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(SchoolClass.objects.count(), 1)

    def test_admin_can_edit_and_deactivate_class(self):
        response = self.client.post(
            reverse('structure:class_edit', args=[self.klass.pk]),
            {'name': 'Form Two', 'is_active': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.klass.refresh_from_db()
        self.assertEqual(self.klass.name, 'Form Two')
        self.assertFalse(self.klass.is_active)
        self.assertTrue(SchoolClass.objects.filter(pk=self.klass.pk).exists())


class StreamAdminTests(StructureAccessBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_admin_can_create_stream(self):
        response = self.client.post(
            reverse('structure:stream_add'), {'name': 'C'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Stream.objects.filter(name='C').exists())

    def test_admin_can_create_class_stream(self):
        stream_b = Stream.objects.create(name='B')
        response = self.client.post(
            reverse('structure:classstream_add'),
            {
                'school_class': self.klass.pk,
                'stream': stream_b.pk,
                'class_teacher': '',
                'subjects': [self.subject.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            ClassStream.objects.filter(
                school_class=self.klass, stream=stream_b
            ).exists()
        )

    def test_duplicate_class_stream_rejected(self):
        response = self.client.post(
            reverse('structure:classstream_add'),
            {
                'school_class': self.klass.pk,
                'stream': self.stream_a.pk,
                'class_teacher': '',
                'subjects': [],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(ClassStream.objects.count(), 1)


class SubjectAdminTests(StructureAccessBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_admin_can_create_subject(self):
        response = self.client.post(
            reverse('structure:subject_add'),
            {'name': 'English', 'code': 'ENG', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Subject.objects.filter(name='English').exists())

    def test_duplicate_subject_name_rejected(self):
        response = self.client.post(
            reverse('structure:subject_add'),
            {'name': 'Mathematics', 'code': 'MTH', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(Subject.objects.count(), 1)

    def test_duplicate_subject_code_rejected(self):
        response = self.client.post(
            reverse('structure:subject_add'),
            {'name': 'Physics', 'code': 'MAT', 'is_active': 'on'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(Subject.objects.count(), 1)

    def test_admin_can_deactivate_subject(self):
        response = self.client.post(
            reverse('structure:subject_edit', args=[self.subject.pk]),
            {'name': 'Mathematics', 'code': 'MAT', 'is_active': ''},
        )
        self.assertEqual(response.status_code, 302)
        self.subject.refresh_from_db()
        self.assertFalse(self.subject.is_active)
        self.assertTrue(self.assignment.class_stream_id)  # assignment preserved


class ClassTeacherAdminTests(StructureAccessBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.teacher2 = Teacher.objects.create(
            employee_no='T002',
            first_name='Grace',
            last_name='Wanjiru',
            gender='F',
            date_joined='2024-03-01',
        )

    def test_admin_can_assign_class_teacher(self):
        response = self.client.post(
            reverse('structure:classstream_edit', args=[self.cs_a.pk]),
            {
                'school_class': self.klass.pk,
                'stream': self.stream_a.pk,
                'class_teacher': self.teacher.pk,
                'subjects': [self.subject.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.cs_a.refresh_from_db()
        self.assertEqual(self.cs_a.class_teacher, self.teacher)

    def test_admin_can_change_class_teacher(self):
        self.cs_a.class_teacher = self.teacher
        self.cs_a.save()
        response = self.client.post(
            reverse('structure:classstream_edit', args=[self.cs_a.pk]),
            {
                'school_class': self.klass.pk,
                'stream': self.stream_a.pk,
                'class_teacher': self.teacher2.pk,
                'subjects': [self.subject.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.cs_a.refresh_from_db()
        self.assertEqual(self.cs_a.class_teacher, self.teacher2)
        self.assertNotEqual(self.cs_a.class_teacher, self.teacher)

    def test_admin_can_remove_class_teacher(self):
        self.cs_a.class_teacher = self.teacher
        self.cs_a.save()
        response = self.client.post(
            reverse('structure:classstream_edit', args=[self.cs_a.pk]),
            {
                'school_class': self.klass.pk,
                'stream': self.stream_a.pk,
                'class_teacher': '',
                'subjects': [self.subject.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.cs_a.refresh_from_db()
        self.assertIsNone(self.cs_a.class_teacher)


class AssignmentAdminTests(StructureAccessBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.subject2 = Subject.objects.create(name='English', code='ENG')

    def test_admin_can_create_assignment(self):
        response = self.client.post(
            reverse('structure:assignment_add'),
            {
                'teacher': self.teacher.pk,
                'class_stream': self.cs_a.pk,
                'subject': self.subject2.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            TeacherAssignment.objects.filter(
                teacher=self.teacher, class_stream=self.cs_a, subject=self.subject2
            ).exists()
        )

    def test_duplicate_assignment_rejected(self):
        response = self.client.post(
            reverse('structure:assignment_add'),
            {
                'teacher': self.teacher.pk,
                'class_stream': self.cs_a.pk,
                'subject': self.subject.pk,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(TeacherAssignment.objects.count(), 1)

    def test_adding_subject_to_stream_does_not_create_assignment(self):
        response = self.client.post(
            reverse('structure:classstream_edit', args=[self.cs_a.pk]),
            {
                'school_class': self.klass.pk,
                'stream': self.stream_a.pk,
                'class_teacher': '',
                'subjects': [self.subject.pk, self.subject2.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TeacherAssignment.objects.count(), 1)
        self.assertEqual(self.cs_a.subjects.count(), 2)

    def test_creating_assignment_does_not_add_subject_to_stream(self):
        response = self.client.post(
            reverse('structure:assignment_add'),
            {
                'teacher': self.teacher.pk,
                'class_stream': self.cs_a.pk,
                'subject': self.subject2.pk,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.cs_a.refresh_from_db()
        self.assertNotIn(self.subject2, self.cs_a.subjects.all())

    def test_admin_can_delete_assignment(self):
        response = self.client.post(
            reverse('structure:assignment_delete', args=[self.assignment.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(TeacherAssignment.objects.count(), 0)
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())


class TeacherViewTests(StructureAccessBase):
    def setUp(self):
        super().setUp()
        self.marks_authorized = TeacherAssignment.objects.filter(
            teacher=self.teacher
        ).count()

    def test_teacher_cannot_access_management_pages(self):
        self.client.force_login(self.teacher_user)
        urls = [
            reverse('structure:class_list'),
            reverse('structure:class_add'),
            reverse('structure:class_edit', args=[self.klass.pk]),
            reverse('structure:stream_list'),
            reverse('structure:classstream_list'),
            reverse('structure:classstream_add'),
            reverse('structure:classstream_edit', args=[self.cs_a.pk]),
            reverse('structure:subject_list'),
            reverse('structure:subject_add'),
            reverse('structure:assignment_list'),
            reverse('structure:assignment_add'),
            reverse('structure:assignment_edit', args=[self.assignment.pk]),
            reverse('structure:assignment_delete', args=[self.assignment.pk]),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, msg=url)

    def test_teacher_cannot_create_assignment_via_post(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(
            reverse('structure:assignment_add'),
            {'teacher': self.teacher.pk, 'class_stream': self.cs_a.pk,
             'subject': self.subject.pk},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            TeacherAssignment.objects.filter(teacher=self.teacher).count(),
            self.marks_authorized,
        )


class ParentAccessTests(StructureAccessBase):
    def test_parent_cannot_access_management_pages(self):
        self.client.force_login(self.parent_user)
        urls = [
            reverse('structure:class_list'),
            reverse('structure:class_add'),
            reverse('structure:classstream_list'),
            reverse('structure:classstream_add'),
            reverse('structure:subject_list'),
            reverse('structure:subject_add'),
            reverse('structure:assignment_list'),
            reverse('structure:assignment_add'),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, msg=url)


class RosterTests(StructureAccessBase):
    def test_class_stream_detail_shows_students_and_teachers(self):
        self.client.force_login(self.admin)
        self._make_student()
        response = self.client.get(
            reverse('structure:classstream_detail', args=[self.cs_a.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Brian Otieno')
        self.assertContains(response, 'John Kamau')
        self.assertContains(response, 'Mathematics')


class NavigationReachabilityTests(StructureAccessBase):
    def test_sidebar_nav_exposes_stream_pages(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('structure:class_list'))
        self.assertContains(response, reverse('structure:stream_list'))
        self.assertContains(response, reverse('structure:classstream_list'))

    def test_class_detail_links_to_stream_setup(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('structure:class_detail', args=[self.klass.pk])
        )
        self.assertContains(response, reverse('structure:stream_list'))
        self.assertContains(response, reverse('structure:classstream_add'))

    def test_class_detail_empty_stream_guides_first_run(self):
        self.client.force_login(self.admin)
        empty_class = SchoolClass.objects.create(name='Form 4')
        response = self.client.get(
            reverse('structure:class_detail', args=[empty_class.pk])
        )
        self.assertContains(response, reverse('structure:stream_add'))
        self.assertContains(response, reverse('structure:classstream_add'))