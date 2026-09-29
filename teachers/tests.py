from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from core.models import (
    ClassStream,
    Department,
    SchoolClass,
    Stream,
    Subject,
    Teacher,
    TeacherAssignment,
)


class TeacherAccessBase(TestCase):
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
        self.dept = Department.objects.create(name='Science', code='SCI')

        self.admin = self._make_user('admin', 'ADMIN')

        self.teacher_user = self._make_user('teacher1', 'TEACHER')
        self.teacher = self._make_teacher(
            'T001', 'John', 'Kamau', user=self.teacher_user
        )
        TeacherAssignment.objects.create(
            teacher=self.teacher, class_stream=self.cs_a, subject=self.subject
        )

        self.parent_user = self._make_user('parent1', 'PARENT')

    def _make_user(self, username, role):
        user = User.objects.create_user(username)
        user.profile.role = role
        user.profile.save()
        return user

    def _make_teacher(self, employee_no, first, last, user=None):
        return Teacher.objects.create(
            user=user,
            employee_no=employee_no,
            first_name=first,
            last_name=last,
            gender='M',
            date_joined='2024-01-10',
            department=self.dept,
        )

    def _teacher_data(self, employee_no='T900', **overrides):
        data = {
            'employee_no': employee_no,
            'first_name': 'Faith',
            'middle_name': '',
            'last_name': 'Njeri',
            'gender': 'F',
            'department': self.dept.id,
            'phone': '',
            'email': '',
            'date_joined': '2026-01-05',
            'classes': [],
        }
        data.update(overrides)
        return data

    def _create_payload(self, user_action='create', **overrides):
        data = self._teacher_data()
        if user_action == 'create':
            data.update({
                'user_action': 'create',
                'username': 'faithn',
                'password1': 'StrongPass!123',
                'password2': 'StrongPass!123',
            })
        elif user_action == 'link':
            data.update({
                'user_action': 'link',
                'link_user': overrides.pop('link_user', ''),
            })
        data.update(overrides)
        return data


class AnonymousAccessTests(TeacherAccessBase):
    def test_anonymous_redirected_to_login(self):
        urls = [
            reverse('teachers:list'),
            reverse('teachers:add'),
            reverse('teachers:detail', args=[self.teacher.pk]),
            reverse('teachers:edit', args=[self.teacher.pk]),
            reverse('teachers:profile'),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])


class AdminCreateTests(TeacherAccessBase):
    def test_admin_can_create_teacher_with_new_account(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('teachers:add'), self._create_payload()
        )
        self.assertEqual(response.status_code, 302)
        teacher = Teacher.objects.get(employee_no='T900')
        self.assertIsNotNone(teacher.user)
        self.assertEqual(teacher.user.username, 'faithn')
        self.assertEqual(teacher.user.profile.role, UserProfile.Roles.TEACHER)
        self.assertTrue(teacher.user.check_password('StrongPass!123'))

    def test_password_mismatch_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('teachers:add'),
            self._create_payload(password1='StrongPass!123', password2='StrongPass!124'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Passwords do not match')
        self.assertFalse(Teacher.objects.filter(employee_no='T900').exists())

    def test_weak_password_rejected_by_validator(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('teachers:add'),
            self._create_payload(password1='12345678', password2='12345678'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Teacher.objects.filter(employee_no='T900').exists())

    def test_duplicate_employee_no_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('teachers:add'),
            self._create_payload(employee_no='T001'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(Teacher.objects.count(), 1)

    def test_duplicate_username_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('teachers:add'),
            self._create_payload(username='teacher1'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already taken')
        self.assertFalse(Teacher.objects.filter(employee_no='T900').exists())

    def test_admin_can_link_existing_teacher_user(self):
        self.client.force_login(self.admin)
        self.other_user = self._make_user('teacher2', 'TEACHER')
        response = self.client.post(
            reverse('teachers:add'),
            self._create_payload(user_action='link', link_user=self.other_user.id),
        )
        self.assertEqual(response.status_code, 302)
        teacher = Teacher.objects.get(employee_no='T900')
        self.assertEqual(teacher.user, self.other_user)
        self.assertEqual(self.other_user.profile.role, UserProfile.Roles.TEACHER)

    def test_superuser_cannot_be_linked(self):
        self.client.force_login(self.admin)
        superuser = User.objects.create_superuser('root', 'root@x.com', 'RootPass!12')
        superuser.profile.role = UserProfile.Roles.TEACHER
        superuser.profile.save()
        response = self.client.post(
            reverse('teachers:add'),
            self._create_payload(user_action='link', link_user=superuser.id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Teacher.objects.filter(employee_no='T900').exists())

    def test_wrong_role_user_cannot_be_linked(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('teachers:add'),
            self._create_payload(user_action='link', link_user=self.parent_user.id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Teacher.objects.filter(employee_no='T900').exists())

    def test_already_linked_user_cannot_be_linked_again(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('teachers:add'),
            self._create_payload(user_action='link', link_user=self.teacher_user.id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Teacher.objects.count(), 1)
        self.assertEqual(
            TeacherAssignment.objects.filter(teacher=self.teacher).count(), 1
        )

    def test_new_teacher_requires_user_action(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('teachers:add'), self._teacher_data()
        )
        self.assertEqual(response.status_code, 200)


class AdminEditTests(TeacherAccessBase):
    def _load_edit_form(self):
        response = self.client.get(
            reverse('teachers:edit', args=[self.teacher.pk])
        )
        self.assertEqual(response.status_code, 200)
        return response

    def test_edit_keep_user_unchanged(self):
        self.client.force_login(self.admin)
        data = self._teacher_data(
            employee_no=self.teacher.employee_no, user_action='keep'
        )
        data['first_name'] = 'John Paul'
        response = self.client.post(
            reverse('teachers:edit', args=[self.teacher.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.first_name, 'John Paul')
        self.assertEqual(self.teacher.user, self.teacher_user)

    def test_relink_switches_user_without_harming_previous(self):
        self.client.force_login(self.admin)
        other_user = self._make_user('teacher2', 'TEACHER')
        data = self._teacher_data(
            employee_no=self.teacher.employee_no,
            user_action='link',
            link_user=other_user.id,
        )
        response = self.client.post(
            reverse('teachers:edit', args=[self.teacher.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.assertEqual(self.teacher.user, other_user)

        self.teacher_user.refresh_from_db()
        self.assertTrue(User.objects.filter(pk=self.teacher_user.pk).exists())
        self.assertTrue(self.teacher_user.is_active)
        self.assertEqual(self.teacher_user.profile.role, UserProfile.Roles.TEACHER)
        self.assertFalse(
            Teacher.objects.filter(pk=self.teacher.pk).filter(
                user=self.teacher_user
            ).exists()
        )

    def test_deactivation_keeps_linked_account_active(self):
        self.client.force_login(self.admin)
        data = self._teacher_data(
            employee_no=self.teacher.employee_no,
            user_action='keep',
            is_active='',
        )
        response = self.client.post(
            reverse('teachers:edit', args=[self.teacher.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.teacher.refresh_from_db()
        self.teacher_user.refresh_from_db()
        self.assertFalse(self.teacher.is_active)
        self.assertTrue(self.teacher_user.is_active)
        self.assertTrue(Teacher.objects.filter(pk=self.teacher.pk).exists())

    def test_class_teacher_assignment(self):
        self.client.force_login(self.admin)
        data = self._teacher_data(
            employee_no='T101', user_action='create', username='newt', 
            password1='StrongPass!123', password2='StrongPass!123',
        )
        data['class_teacher_for'] = self.cs_a.id
        response = self.client.post(reverse('teachers:add'), data)
        self.assertEqual(response.status_code, 302)
        teacher = Teacher.objects.get(employee_no='T101')
        self.cs_a.refresh_from_db()
        self.assertEqual(self.cs_a.class_teacher, teacher)

    def test_subject_assignments_saved_with_teacher(self):
        self.client.force_login(self.admin)
        data = self._create_payload()
        data.update({
            'assignments-TOTAL_FORMS': '1',
            'assignments-INITIAL_FORMS': '0',
            'assignments-MIN_NUM_FORMS': '0',
            'assignments-MAX_NUM_FORMS': '1000',
            'assignments-0-class_stream': self.cs_a.id,
            'assignments-0-subject': self.subject.id,
        })
        response = self.client.post(reverse('teachers:add'), data)
        self.assertEqual(response.status_code, 302)
        teacher = Teacher.objects.get(employee_no='T900')
        assignment = TeacherAssignment.objects.filter(teacher=teacher).first()
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.class_stream, self.cs_a)
        self.assertEqual(assignment.subject, self.subject)

    def test_class_teachership_does_not_create_subject_assignment(self):
        self.client.force_login(self.admin)
        data = self._teacher_data(
            employee_no='T101', user_action='create', username='newt',
            password1='StrongPass!123', password2='StrongPass!123',
        )
        data['class_teacher_for'] = self.cs_a.id
        response = self.client.post(reverse('teachers:add'), data)
        self.assertEqual(response.status_code, 302)
        teacher = Teacher.objects.get(employee_no='T101')
        self.assertEqual(teacher.assignments.count(), 0)


class AdminEditTeachershipTests(TeacherAccessBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.cs_a.class_teacher = self.teacher
        self.cs_a.save(update_fields=['class_teacher'])

    def test_edit_form_prefills_current_teachership(self):
        response = self.client.get(
            reverse('teachers:edit', args=[self.teacher.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'<option value="{self.cs_a.pk}" selected>',
            html=False,
        )

    def test_edit_unchanged_field_keeps_teachership(self):
        data = self._teacher_data(
            employee_no=self.teacher.employee_no, user_action='keep',
        )
        data['first_name'] = 'John Paul'
        data['class_teacher_for'] = self.cs_a.id
        response = self.client.post(
            reverse('teachers:edit', args=[self.teacher.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.cs_a.refresh_from_db()
        self.assertEqual(self.cs_a.class_teacher, self.teacher)

    def test_edit_clears_teachership_when_deselected(self):
        data = self._teacher_data(
            employee_no=self.teacher.employee_no, user_action='keep',
        )
        data['class_teacher_for'] = ''
        response = self.client.post(
            reverse('teachers:edit', args=[self.teacher.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.cs_a.refresh_from_db()
        self.assertIsNone(self.cs_a.class_teacher)

    def test_edit_moves_teachership_to_another_stream(self):
        data = self._teacher_data(
            employee_no=self.teacher.employee_no, user_action='keep',
        )
        data['class_teacher_for'] = self.cs_b.id
        response = self.client.post(
            reverse('teachers:edit', args=[self.teacher.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        self.cs_a.refresh_from_db()
        self.cs_b.refresh_from_db()
        self.assertIsNone(self.cs_a.class_teacher)
        self.assertEqual(self.cs_b.class_teacher, self.teacher)


class TeacherAccessTests(TeacherAccessBase):
    def test_teacher_can_view_own_profile(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('teachers:profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'John Kamau')

    def test_teacher_can_view_own_detail(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(
            reverse('teachers:detail', args=[self.teacher.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_teacher_cannot_view_another_teacher_detail(self):
        self.client.force_login(self.teacher_user)
        other = self._make_teacher('T099', 'Grace', 'Wanjiru')
        response = self.client.get(reverse('teachers:detail', args=[other.pk]))
        self.assertEqual(response.status_code, 403)

    def test_teacher_cannot_use_admin_manage_pages(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(
            self.client.get(reverse('teachers:list')).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse('teachers:add')).status_code, 403
        )


class ParentAccessTests(TeacherAccessBase):
    def test_parent_cannot_access_teacher_pages(self):
        self.client.force_login(self.parent_user)
        urls = [
            reverse('teachers:list'),
            reverse('teachers:add'),
            reverse('teachers:detail', args=[self.teacher.pk]),
            reverse('teachers:edit', args=[self.teacher.pk]),
            reverse('teachers:profile'),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)