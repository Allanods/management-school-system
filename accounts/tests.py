from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile
from core.models import Department, Teacher
from students.models import Parent
from .services import (
    activate_account,
    create_user_account,
    deactivate_account,
    eligible_parent_records,
    eligible_teacher_records,
    eligible_users_for_link,
    link_user_to_persona,
    school_persona_for,
    set_account_password,
    unlink_user,
)


class AccountManagementBase(TestCase):
    def setUp(self):
        self.admin = self._make_user('admin', 'ADMIN')
        self.teacher_user = self._make_user('teacher1', 'TEACHER')
        self.parent_user = self._make_user('parent1', 'PARENT')
        self.superuser = User.objects.create_superuser(
            'root', 'root@x.com', 'RootPass!123'
        )

        self.dept = Department.objects.create(name='Science', code='SCI')
        self.teacher = self._make_teacher(
            'T001', 'John', 'Kamau', user=self.teacher_user
        )
        self.unlinked_teacher = self._make_teacher('T002', 'Grace', 'Wanjiru')
        self.parent = self._make_parent(
            'Jane', 'Otieno', user=self.parent_user
        )
        self.unlinked_parent = self._make_parent('Mary', 'Wanjiku')

    def _make_user(self, username, role):
        user = User.objects.create_user(username)
        user.profile.role = role
        user.profile.save()
        return user

    def _make_teacher(self, employee_no, first, last, user=None):
        return Teacher.objects.create(
            user=user, employee_no=employee_no, first_name=first,
            last_name=last, gender='F', date_joined='2025-01-10',
            department=self.dept,
        )

    def _make_parent(self, first, last, user=None):
        return Parent.objects.create(
            user=user, first_name=first, last_name=last, phone='0700000000',
        )

    def _login(self, user):
        self.client.force_login(user)

    def _create_payload(self, username='newuser', role='TEACHER',
                        record=None, password='StrongPass!123', **overrides):
        payload = {
            'role': role,
            'username': username,
            'email': '',
            'password1': password,
            'password2': password,
            'teacher': '',
            'parent': '',
        }
        if role == 'TEACHER':
            payload['teacher'] = (
                record.pk if record else self.unlinked_teacher.pk
            )
        else:
            payload['parent'] = (
                record.pk if record else self.unlinked_parent.pk
            )
        payload.update(overrides)
        return payload


class AuthorizationTests(AccountManagementBase):
    def test_anonymous_redirected_to_login(self):
        urls = [
            reverse('accounts:user_list'),
            reverse('accounts:user_add'),
            reverse('accounts:user_detail', args=[self.teacher_user.pk]),
            reverse('accounts:user_password', args=[self.teacher_user.pk]),
            reverse('accounts:user_toggle_active', args=[self.teacher_user.pk]),
            reverse('accounts:user_link', args=[self.teacher_user.pk]),
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])

    def test_anonymous_post_mutations_redirected(self):
        for name, pk in [
            ('user_toggle_active', self.teacher_user.pk),
            ('user_link', self.teacher_user.pk),
        ]:
            response = self.client.post(reverse(f'accounts:{name}', args=[pk]))
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.headers['Location'])

    def test_teacher_gets_403_on_all_account_pages(self):
        self._login(self.teacher_user)
        urls = [
            reverse('accounts:user_list'),
            reverse('accounts:user_add'),
            reverse('accounts:user_detail', args=[self.teacher_user.pk]),
            reverse('accounts:user_password', args=[self.teacher_user.pk]),
        ]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_teacher_cannot_post_mutations(self):
        self._login(self.teacher_user)
        for name, pk in [
            ('user_toggle_active', self.teacher_user.pk),
            ('user_link', self.teacher_user.pk),
        ]:
            response = self.client.post(reverse(f'accounts:{name}', args=[pk]))
            self.assertEqual(response.status_code, 403)

    def test_parent_gets_403_on_account_pages(self):
        self._login(self.parent_user)
        for url in [
            reverse('accounts:user_list'),
            reverse('accounts:user_add'),
            reverse('accounts:user_detail', args=[self.parent_user.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_can_access_all_account_pages(self):
        self._login(self.admin)
        for url in [
            reverse('accounts:user_list'),
            reverse('accounts:user_add'),
            reverse('accounts:user_detail', args=[self.teacher_user.pk]),
            reverse('accounts:user_password', args=[self.teacher_user.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200)


class EligibilityServiceTests(AccountManagementBase):
    def test_eligible_teacher_records_excludes_linked(self):
        records = list(eligible_teacher_records())
        self.assertIn(self.unlinked_teacher, records)
        self.assertNotIn(self.teacher, records)

    def test_eligible_parent_records_excludes_linked(self):
        records = list(eligible_parent_records())
        self.assertIn(self.unlinked_parent, records)
        self.assertNotIn(self.parent, records)

    def test_eligible_users_for_link_teacher(self):
        free_teacher = self._make_user('free_teacher', 'TEACHER')
        linked_teacher_user = self._make_user('other_teacher', 'TEACHER')
        self._make_teacher(
            'T003', 'Paul', 'Njeri', user=linked_teacher_user
        )
        fake_super = User.objects.create_superuser(
            'su2', 'su2@x.com', 'SuperPass!12'
        )
        eligible = list(eligible_users_for_link('teacher'))
        self.assertIn(free_teacher, eligible)
        self.assertNotIn(self.teacher_user, eligible)
        self.assertNotIn(linked_teacher_user, eligible)
        self.assertNotIn(self.parent_user, eligible)
        self.assertNotIn(fake_super, eligible)

    def test_eligible_users_for_link_parent(self):
        free_parent = self._make_user('free_parent', 'PARENT')
        linked_parent_user = self._make_user('other_parent', 'PARENT')
        self._make_parent('Ann', 'Wairimu', user=linked_parent_user)
        eligible = list(eligible_users_for_link('parent'))
        self.assertIn(free_parent, eligible)
        self.assertNotIn(self.parent_user, eligible)
        self.assertNotIn(linked_parent_user, eligible)
        self.assertNotIn(self.teacher_user, eligible)

    def test_school_persona_for_teacher(self):
        kind, record = school_persona_for(self.teacher_user)
        self.assertEqual(kind, 'teacher')
        self.assertEqual(record, self.teacher)

    def test_school_persona_for_parent(self):
        kind, record = school_persona_for(self.parent_user)
        self.assertEqual(kind, 'parent')
        self.assertEqual(record, self.parent)

    def test_school_persona_for_unlinked_user(self):
        kind, record = school_persona_for(self.admin)
        self.assertIsNone(kind)
        self.assertIsNone(record)

    def test_school_persona_for_anonymous(self):
        self.assertIsNone(school_persona_for(None)[0])


class CreateAccountViewTests(AccountManagementBase):
    def test_admin_can_create_teacher_account(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_add'), self._create_payload()
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='newuser')
        self.assertEqual(user.profile.role, UserProfile.Roles.TEACHER)
        self.assertEqual(user.teacher, self.unlinked_teacher)
        self.assertTrue(user.check_password('StrongPass!123'))
        self.assertTrue(user.is_active)

    def test_admin_can_create_parent_account(self):
        self._login(self.admin)
        payload = self._create_payload(role='PARENT')
        response = self.client.post(reverse('accounts:user_add'), payload)
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='newuser')
        self.assertEqual(user.profile.role, UserProfile.Roles.PARENT)
        self.assertEqual(user.parent, self.unlinked_parent)

    def test_password_is_hashed(self):
        self._login(self.admin)
        self.client.post(
            reverse('accounts:user_add'), self._create_payload()
        )
        user = User.objects.get(username='newuser')
        self.assertNotEqual(user.password, 'StrongPass!123')
        self.assertTrue(user.password.startswith('pbkdf2_'))
        self.assertTrue(user.check_password('StrongPass!123'))

    def test_weak_password_rejected(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_add'),
            self._create_payload(password='12345678'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_mismatched_password_rejected(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_add'),
            self._create_payload(password2='Different1!'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_duplicate_username_rejected(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_add'),
            self._create_payload(username='teacher1'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username='teacher1').count(), 1)

    def test_cannot_create_admin_account(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_add'),
            self._create_payload(role='ADMIN'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Only Teacher and Parent')
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_cannot_create_without_eligible_record(self):
        self._login(self.admin)
        payload = self._create_payload()
        payload['teacher'] = self.teacher.pk
        response = self.client.post(reverse('accounts:user_add'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_role_persona_mismatch_rejected(self):
        self._login(self.admin)
        payload = self._create_payload(role='PARENT')
        payload['parent'] = ''
        payload['teacher'] = self.unlinked_teacher.pk
        response = self.client.post(reverse('accounts:user_add'), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_creation_never_auto_creates_school_record(self):
        self._login(self.admin)
        payload = self._create_payload(role='PARENT')
        self.client.post(reverse('accounts:user_add'), payload)
        self.assertEqual(Parent.objects.count(), 2)
        self.assertEqual(Teacher.objects.count(), 2)


class CreateAccountServiceTests(AccountManagementBase):
    def test_service_create_teacher_links_record(self):
        user = create_user_account(
            'svct', 'StrongPass!123', UserProfile.Roles.TEACHER,
            record=self.unlinked_teacher,
        )
        self.assertEqual(user.profile.role, UserProfile.Roles.TEACHER)
        self.assertEqual(self.unlinked_teacher.user, user)
        self.assertTrue(user.is_active)

    def test_service_rejects_wrong_role(self):
        with self.assertRaises(ValidationError):
            create_user_account(
                'bad', 'StrongPass!123', UserProfile.Roles.ADMIN,
                record=self.unlinked_teacher,
            )

    def test_service_rejects_wrong_record_type(self):
        with self.assertRaises(ValidationError):
            create_user_account(
                'bad', 'StrongPass!123', UserProfile.Roles.TEACHER,
                record=self.unlinked_parent,
            )

    def test_service_rejects_already_linked_record(self):
        with self.assertRaises(ValidationError):
            create_user_account(
                'bad', 'StrongPass!123', UserProfile.Roles.TEACHER,
                record=self.teacher,
            )

    def test_service_rejects_without_record(self):
        with self.assertRaises(ValidationError):
            create_user_account('bad', 'StrongPass!123',
                                UserProfile.Roles.TEACHER)


class LinkUnlinkTests(AccountManagementBase):
    def test_link_eligible_teacher(self):
        self._login(self.admin)
        target = self._make_user('freelink_t', 'TEACHER')
        response = self.client.post(
            reverse('accounts:user_link', args=[target.pk]),
            {'record': self.unlinked_teacher.pk},
        )
        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.unlinked_teacher.refresh_from_db()
        self.assertEqual(getattr(target, 'teacher', None), self.unlinked_teacher)
        self.assertEqual(self.unlinked_teacher.user, target)

    def test_link_eligible_parent(self):
        self._login(self.admin)
        target = self._make_user('freelink_p', 'PARENT')
        response = self.client.post(
            reverse('accounts:user_link', args=[target.pk]),
            {'record': self.unlinked_parent.pk},
        )
        self.assertEqual(response.status_code, 302)
        target.refresh_from_db()
        self.unlinked_parent.refresh_from_db()
        self.assertEqual(getattr(target, 'parent', None), self.unlinked_parent)
        self.assertEqual(self.unlinked_parent.user, target)

    def test_cannot_relink_already_linked_teacher_record(self):
        self._login(self.admin)
        owner = self._make_user('owner_t', 'TEACHER')
        self.unlinked_teacher.user = owner
        self.unlinked_teacher.save(update_fields=['user'])
        other = self._make_user('free', 'TEACHER')
        response = self.client.post(
            reverse('accounts:user_link', args=[other.pk]),
            {'record': self.unlinked_teacher.pk},
        )
        self.assertEqual(response.status_code, 302)
        other.refresh_from_db()
        self.assertIsNone(getattr(other, 'teacher', None))

    def test_cannot_link_wrong_role_user(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_link', args=[self.parent_user.pk]),
            {'record': self.unlinked_teacher.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.parent_user.refresh_from_db()
        self.assertIsNone(getattr(self.parent_user, 'teacher', None))
        self.unlinked_teacher.refresh_from_db()
        self.assertIsNone(self.unlinked_teacher.user)

    def test_cannot_link_superuser(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_link', args=[self.superuser.pk]),
            {'record': self.unlinked_teacher.pk},
        )
        self.assertEqual(response.status_code, 403)
        self.unlinked_teacher.refresh_from_db()
        self.assertIsNone(self.unlinked_teacher.user)

    def test_cannot_link_user_already_linked_to_another_persona(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_link', args=[self.teacher_user.pk]),
            {'record': self.unlinked_parent.pk},
        )
        self.assertEqual(response.status_code, 302)
        self.teacher_user.refresh_from_db()
        self.assertEqual(self.teacher_user.teacher, self.teacher)
        self.unlinked_parent.refresh_from_db()
        self.assertIsNone(self.unlinked_parent.user)

    def test_unlink_teacher(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_link', args=[self.teacher_user.pk]),
            {'action': 'unlink'},
        )
        self.assertEqual(response.status_code, 302)
        self.teacher_user.refresh_from_db()
        self.teacher.refresh_from_db()
        self.assertIsNone(getattr(self.teacher_user, 'teacher', None))
        self.assertIsNone(self.teacher.user)
        self.assertTrue(User.objects.filter(pk=self.teacher_user.pk).exists())
        self.assertTrue(Teacher.objects.filter(pk=self.teacher.pk).exists())

    def test_unlink_parent(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_link', args=[self.parent_user.pk]),
            {'action': 'unlink'},
        )
        self.assertEqual(response.status_code, 302)
        self.parent_user.refresh_from_db()
        self.parent.refresh_from_db()
        self.assertIsNone(getattr(self.parent_user, 'parent', None))
        self.assertIsNone(self.parent.user)

    def test_unlink_superuser_rejected(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_link', args=[self.superuser.pk]),
            {'action': 'unlink'},
        )
        self.assertEqual(response.status_code, 403)


class AccountStatusTests(AccountManagementBase):
    def test_admin_can_deactivate_user(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_toggle_active',
                    args=[self.teacher_user.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.teacher_user.refresh_from_db()
        self.assertFalse(self.teacher_user.is_active)

    def test_admin_can_activate_user(self):
        self.teacher_user.is_active = False
        self.teacher_user.save(update_fields=['is_active'])
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_toggle_active',
                    args=[self.teacher_user.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.teacher_user.refresh_from_db()
        self.assertTrue(self.teacher_user.is_active)

    def test_inactive_user_cannot_log_in(self):
        self.teacher_user.set_password('OldPass!123')
        self.teacher_user.is_active = False
        self.teacher_user.save()
        ok = self.client.login(username='teacher1', password='OldPass!123')
        self.assertFalse(ok)

    def test_active_user_can_log_in(self):
        self.teacher_user.set_password('OldPass!123')
        self.teacher_user.save()
        ok = self.client.login(username='teacher1', password='OldPass!123')
        self.assertTrue(ok)

    def test_deactivation_keeps_teacher_record_untouched(self):
        self._login(self.admin)
        self.client.post(
            reverse('accounts:user_toggle_active',
                    args=[self.teacher_user.pk])
        )
        self.teacher.refresh_from_db()
        self.teacher_user.refresh_from_db()
        self.assertFalse(self.teacher_user.is_active)
        self.assertTrue(self.teacher.is_active)
        self.assertEqual(self.teacher.user, self.teacher_user)

    def test_deactivation_keeps_parent_record_untouched(self):
        self._login(self.admin)
        self.client.post(
            reverse('accounts:user_toggle_active',
                    args=[self.parent_user.pk])
        )
        self.parent.refresh_from_db()
        self.parent_user.refresh_from_db()
        self.assertFalse(self.parent_user.is_active)
        self.assertEqual(self.parent.user, self.parent_user)

    def test_activation_does_not_touch_teacher_record(self):
        self._login(self.admin)
        self.client.post(
            reverse('accounts:user_toggle_active',
                    args=[self.teacher_user.pk])
        )
        self.teacher_user.refresh_from_db()
        self.assertFalse(self.teacher_user.is_active)
        self.client.post(
            reverse('accounts:user_toggle_active',
                    args=[self.teacher_user.pk])
        )
        self.teacher_user.refresh_from_db()
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher_user.is_active)
        self.assertTrue(self.teacher.is_active)

    def test_deactivate_service_is_noop_when_inactive(self):
        self.teacher_user.is_active = False
        self.teacher_user.save(update_fields=['is_active'])
        deactivate_account(self.teacher_user)
        self.teacher_user.refresh_from_db()
        self.assertFalse(self.teacher_user.is_active)

    def test_activate_service_does_not_touch_teacher(self):
        self.teacher_user.is_active = False
        self.teacher_user.save(update_fields=['is_active'])
        self.teacher.is_active = False
        self.teacher.save(update_fields=['is_active'])
        activate_account(self.teacher_user)
        self.teacher_user.refresh_from_db()
        self.teacher.refresh_from_db()
        self.assertTrue(self.teacher_user.is_active)
        self.assertFalse(self.teacher.is_active)


class PasswordTests(AccountManagementBase):
    def _password_page(self, user, password='NewPass!456'):
        payload = {'new_password1': password, 'new_password2': password}
        return self.client.post(
            reverse('accounts:user_password', args=[user.pk]), payload
        )

    def test_admin_can_reset_password(self):
        self.teacher_user.set_password('OldPass!123')
        self.teacher_user.save()
        self._login(self.admin)
        response = self._password_page(self.teacher_user, 'NewPass!456')
        self.assertEqual(response.status_code, 302)
        self.teacher_user.refresh_from_db()
        self.assertTrue(self.teacher_user.check_password('NewPass!456'))
        self.assertFalse(self.teacher_user.check_password('OldPass!123'))

    def test_new_password_is_hashed(self):
        self._login(self.admin)
        self._password_page(self.teacher_user, 'NewPass!456')
        self.teacher_user.refresh_from_db()
        self.assertNotEqual(self.teacher_user.password, 'NewPass!456')
        self.assertTrue(self.teacher_user.password.startswith('pbkdf2_'))

    def test_weak_password_rejected(self):
        self._login(self.admin)
        response = self._password_page(self.teacher_user, '12345678')
        self.assertEqual(response.status_code, 200)
        self.teacher_user.refresh_from_db()
        self.assertFalse(self.teacher_user.check_password('12345678'))

    def test_mismatched_password_rejected(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_password', args=[self.teacher_user.pk]),
            {'new_password1': 'NewPass!456', 'new_password2': 'NewPass!999'},
        )
        self.assertEqual(response.status_code, 200)
        self.teacher_user.refresh_from_db()
        self.assertFalse(self.teacher_user.check_password('NewPass!456'))

    def test_password_never_rendered(self):
        self._login(self.admin)
        response = self._password_page(self.teacher_user, 'NewPass!456')
        content = response.content.decode()
        self.assertNotIn('NewPass!456', content)
        self.assertNotIn(self.teacher_user.password, content)

    def test_password_page_admin_only(self):
        self._login(self.teacher_user)
        response = self._password_page(self.admin, 'NewPass!456')
        self.assertEqual(response.status_code, 403)

    def test_superuser_password_cannot_be_reset(self):
        self._login(self.admin)
        response = self._password_page(self.superuser, 'NewPass!456')
        self.assertEqual(response.status_code, 403)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.check_password('RootPass!123'))

    def test_set_account_password_service(self):
        set_account_password(self.teacher_user, 'ServicePass!9')
        self.teacher_user.refresh_from_db()
        self.assertTrue(self.teacher_user.check_password('ServicePass!9'))
        self.assertFalse(self.teacher_user.check_password(''))

    def test_self_service_password_change_works(self):
        self.teacher_user.set_password('OldPass!123')
        self.teacher_user.save()
        self._login(self.teacher_user)
        response = self.client.post(
            reverse('accounts:password_change'),
            {
                'old_password': 'OldPass!123',
                'new_password1': 'SelfNew!456',
                'new_password2': 'SelfNew!456',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.teacher_user.refresh_from_db()
        self.assertTrue(self.teacher_user.check_password('SelfNew!456'))

    def test_self_service_password_change_requires_login(self):
        response = self.client.get(reverse('accounts:password_change'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.headers['Location'])

    def test_self_service_password_change_allows_teacher_and_parent(self):
        for user in (self.teacher_user, self.parent_user):
            user.set_password('OldPass!123')
            user.save()
            self._login(user)
            response = self.client.post(
                reverse('accounts:password_change'),
                {
                    'old_password': 'OldPass!123',
                    'new_password1': 'SelfNew!456',
                    'new_password2': 'SelfNew!456',
                },
            )
            self.assertEqual(response.status_code, 302)
            user.refresh_from_db()
            self.assertTrue(user.check_password('SelfNew!456'))


class PasswordResetFlowTests(AccountManagementBase):
    def test_reset_request_page_renders(self):
        response = self.client.get(reverse('accounts:password_reset'))
        self.assertEqual(response.status_code, 200)

    def test_reset_sends_email_and_redirects_to_done(self):
        self.parent_user.set_password('OldPass!1')
        self.parent_user.email = 'jane@example.com'
        self.parent_user.save(update_fields=['email', 'password'])
        response = self.client.post(reverse('accounts:password_reset'), {
            'email': 'jane@example.com',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('accounts:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('jane@example.com', mail.outbox[0].to)

    def test_reset_does_not_leak_whether_email_exists(self):
        response = self.client.post(reverse('accounts:password_reset'), {
            'email': 'nobody@example.com',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_confirm_sets_new_password(self):
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        self.parent_user.set_password('OldPass!1')
        self.parent_user.save()

        uidb64 = urlsafe_base64_encode(force_bytes(self.parent_user.pk))
        token = default_token_generator.make_token(self.parent_user)
        link = reverse('accounts:password_reset_confirm', args=[uidb64, token])

        response = self.client.get(link)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/set-password/', response.url)

        response = self.client.post(
            response.url,
            {
                'new_password1': 'FreshPass!99',
                'new_password2': 'FreshPass!99',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('accounts:password_reset_complete'))
        self.parent_user.refresh_from_db()
        self.assertTrue(self.parent_user.check_password('FreshPass!99'))

    def test_login_page_links_to_reset(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertContains(response, reverse('accounts:password_reset'))

    def test_topbar_links_to_password_change(self):
        from django.urls import reverse as r
        self.parent_user.set_password('OldPass!1')
        self.parent_user.save()
        self._login(self.parent_user)
        response = self.client.get(r('accounts:dashboard'))
        self.assertContains(response, r('accounts:password_change'))


class NavHighlightTests(AccountManagementBase):
    def _nav(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return {item['key']: item for item in response.context['nav_items']}

    def test_parent_detail_highlights_parents_not_students(self):
        self._login(self.admin)
        nav = self._nav(reverse('students:parent_detail', args=[self.parent.pk]))
        self.assertTrue(nav['parents']['active'])
        self.assertFalse(nav['students']['active'])

    def test_student_list_highlights_students_not_parents(self):
        self._login(self.admin)
        nav = self._nav(reverse('students:list'))
        self.assertTrue(nav['students']['active'])
        self.assertFalse(nav['parents']['active'])

    def test_active_entry_exact_or_longest_prefix(self):
        self._login(self.admin)
        nav = self._nav(reverse('academics:gradeband_list'))
        self.assertTrue(nav['grade_bands']['active'])
        self.assertFalse(nav['academics']['active'])


class SuperuserProtectionTests(AccountManagementBase):
    def test_superuser_cannot_be_toggled(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_toggle_active', args=[self.superuser.pk])
        )
        self.assertEqual(response.status_code, 403)
        self.superuser.refresh_from_db()
        self.assertTrue(self.superuser.is_active)

    def test_superuser_cannot_be_unlinked(self):
        self._login(self.admin)
        response = self.client.post(
            reverse('accounts:user_link', args=[self.superuser.pk]),
            {'action': 'unlink'},
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_cannot_have_password_reset(self):
        self._login(self.admin)
        response = self.client.get(
            reverse('accounts:user_password', args=[self.superuser.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_superuser_row_is_read_only_on_detail_page(self):
        self._login(self.admin)
        response = self.client.get(
            reverse('accounts:user_detail', args=[self.superuser.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'read-only')


class AccountListViewTests(AccountManagementBase):
    def test_list_shows_all_users(self):
        self._login(self.admin)
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'admin')
        self.assertContains(response, 'teacher1')
        self.assertContains(response, 'parent1')
        self.assertContains(response, 'root')

    def test_list_filters_by_role(self):
        self._login(self.admin)
        response = self.client.get(
            reverse('accounts:user_list'), {'role': 'TEACHER'}
        )
        self.assertContains(response, 'teacher1')
        self.assertContains(response, 'John Kamau')
        self.assertNotContains(response, 'Jane Otieno')

    def test_list_filters_by_active(self):
        self.teacher_user.is_active = False
        self.teacher_user.save(update_fields=['is_active'])
        self._login(self.admin)
        response = self.client.get(
            reverse('accounts:user_list'), {'active': '0'}
        )
        self.assertContains(response, 'teacher1')
        self.assertNotContains(response, 'parent1')

    def test_list_filters_by_linked_status(self):
        self._login(self.admin)
        response = self.client.get(
            reverse('accounts:user_list'), {'linked': 'unlinked'}
        )
        self.assertContains(response, 'admin')
        self.assertNotContains(response, 'teacher1')
        self.assertNotContains(response, 'parent1')

    def test_list_search(self):
        self._login(self.admin)
        response = self.client.get(
            reverse('accounts:user_list'), {'q': 'teacher1'}
        )
        self.assertContains(response, 'teacher1')
        self.assertNotContains(response, 'Jane Otieno')

    def test_list_search_matches_linked_person_name(self):
        self._login(self.admin)
        response = self.client.get(
            reverse('accounts:user_list'), {'q': 'kamau'}
        )
        self.assertContains(response, 'teacher1')
        self.assertNotContains(response, 'Jane Otieno')

    def test_pagination(self):
        for i in range(30):
            self._make_user(f'bulk{i}', 'PARENT')
        self._login(self.admin)
        response = self.client.get(reverse('accounts:user_list'))
        self.assertEqual(
            response.context['page_obj'].paginator.per_page, 25
        )


class UnlinkServiceTests(AccountManagementBase):
    def test_unlink_preserves_all_records(self):
        unlink_user(self.teacher_user)
        self.assertTrue(User.objects.filter(pk=self.teacher_user.pk).exists())
        self.assertTrue(Teacher.objects.filter(pk=self.teacher.pk).exists())
        self.teacher.refresh_from_db()
        self.assertIsNone(self.teacher.user)
        self.teacher_user.refresh_from_db()
        self.assertIsNone(getattr(self.teacher_user, 'teacher', None))

    def test_unlink_superuser_rejected(self):
        with self.assertRaises(ValidationError):
            unlink_user(self.superuser)