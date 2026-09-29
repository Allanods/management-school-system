from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.access import ADMIN, PARENT, TEACHER
from .models import Announcement
from .services import (
    audiences_for_user,
    can_delete_announcement,
    can_view_announcement,
    publish_announcement,
    unpublish_announcement,
    visible_announcements,
)


class AnnouncementBase(TestCase):
    def setUp(self):
        self.admin = self._make_user('admin', ADMIN)
        self.teacher = self._make_user('teacher', TEACHER)
        self.parent = self._make_user('parent', PARENT)

    def _make_user(self, username, role):
        user = User.objects.create_user(username)
        user.profile.role = role
        user.profile.save()
        return user

    def _announcement(self, audience='ALL', published=True, author=None,
                      title=None):
        return Announcement.objects.create(
            title=title or f'Notice {audience}',
            message='Something important for everyone.',
            audience=audience,
            published=published,
            published_at=timezone.now() if published else None,
            created_by=author or self.admin,
        )

    def _login(self, user):
        self.client.force_login(user)

    def _list(self):
        return self.client.get(reverse('announcements:list'))

    def _detail(self, pk):
        return self.client.get(reverse('announcements:detail', args=[pk]))

    def _post(self, name, pk):
        return self.client.post(reverse(f'announcements:{name}', args=[pk]))


class AnnouncementAudienceAndVisibilityTests(AnnouncementBase):
    """Who sees which announcements."""

    def test_admin_audiences_include_all(self):
        self.assertEqual(
            audiences_for_user(self.admin),
            {Announcement.Audience.ALL, Announcement.Audience.TEACHERS,
             Announcement.Audience.PARENTS},
        )

    def test_teacher_audiences_exclude_parents(self):
        self.assertEqual(
            audiences_for_user(self.teacher),
            {Announcement.Audience.ALL, Announcement.Audience.TEACHERS},
        )

    def test_parent_audiences_exclude_teachers(self):
        self.assertEqual(
            audiences_for_user(self.parent),
            {Announcement.Audience.ALL, Announcement.Audience.PARENTS},
        )

    def test_anonymous_user_has_no_audiences(self):
        self.assertEqual(audiences_for_user(None), set())

    def test_admin_sees_all_records_including_drafts(self):
        self._announcement('ALL', published=True)
        self._announcement('TEACHERS', published=True)
        self._announcement('PARENTS', published=True)
        self._announcement('ALL', published=False)
        self.assertEqual(visible_announcements(self.admin).count(), 4)

    def test_teacher_sees_all_and_teacher_published_only(self):
        self._announcement('ALL', published=True)
        self._announcement('TEACHERS', published=True)
        self._announcement('PARENTS', published=True)
        self._announcement('ALL', published=False)
        titles = set(visible_announcements(self.teacher).values_list('title',
                                                                    flat=True))
        self.assertEqual(titles, {'Notice ALL', 'Notice TEACHERS'})

    def test_parent_sees_all_and_parent_published_only(self):
        self._announcement('ALL', published=True)
        self._announcement('TEACHERS', published=True)
        self._announcement('PARENTS', published=True)
        self._announcement('PARENTS', published=False)
        titles = set(visible_announcements(self.parent).values_list('title',
                                                                    flat=True))
        self.assertEqual(titles, {'Notice ALL', 'Notice PARENTS'})

    def test_anonymous_user_sees_nothing(self):
        self._announcement('ALL', published=True)
        self.assertEqual(visible_announcements(None).count(), 0)

    def test_can_view_admin_sees_every_record(self):
        published = self._announcement('PARENTS', published=True)
        draft = self._announcement('TEACHERS', published=False)
        self.assertTrue(can_view_announcement(self.admin, published))
        self.assertTrue(can_view_announcement(self.admin, draft))

    def test_can_view_teacher_rejects_parent_and_draft(self):
        teacher_all = self._announcement('TEACHERS', published=True)
        parents = self._announcement('PARENTS', published=True)
        draft = self._announcement('ALL', published=False)
        self.assertTrue(can_view_announcement(self.teacher, teacher_all))
        self.assertFalse(can_view_announcement(self.teacher, parents))
        self.assertFalse(can_view_announcement(self.teacher, draft))

    def test_can_view_parent_rejects_teacher_audience(self):
        teacher_only = self._announcement('TEACHERS', published=True)
        parents = self._announcement('PARENTS', published=True)
        self.assertFalse(can_view_announcement(self.parent, teacher_only))
        self.assertTrue(can_view_announcement(self.parent, parents))

    def test_can_view_rejects_anonymous(self):
        published = self._announcement('ALL', published=True)
        self.assertFalse(can_view_announcement(None, published))

    def test_default_ordering_newest_published_first(self):
        first = self._announcement('ALL', published=True)
        second = self._announcement('ALL', published=True)
        first.published_at = timezone.now() - timezone.timedelta(days=2)
        first.save(update_fields=['published_at'])
        self.assertEqual(list(visible_announcements(self.admin)), [second,
                                                                   first])


class AnnouncementListViewTests(AnnouncementBase):
    def test_anonymous_redirected_to_login(self):
        response = self._list()
        self.assertRedirects(response, f"/accounts/login/?next={reverse('announcements:list')}")

    def test_teacher_list_contains_only_their_audience(self):
        self._announcement('TEACHERS', published=True)
        self._announcement('PARENTS', published=True)
        self._login(self.teacher)
        response = self._list()
        self.assertContains(response, 'Notice TEACHERS')
        self.assertNotContains(response, 'Notice PARENTS')

    def test_parent_list_contains_only_their_audience(self):
        self._announcement('PARENTS', published=True)
        self._announcement('TEACHERS', published=True)
        self._login(self.parent)
        response = self._list()
        self.assertContains(response, 'Notice PARENTS')
        self.assertNotContains(response, 'Notice TEACHERS')

    def test_parent_list_hides_drafts(self):
        self._announcement('ALL', published=False, title='Hidden draft')
        self._login(self.parent)
        self.assertNotContains(self._list(), 'Hidden draft')

    def test_admin_list_contains_drafts_and_published(self):
        self._announcement('ALL', published=True, title='How published')
        self._announcement('TEACHERS', published=False, title='How draft')
        self._login(self.admin)
        response = self._list()
        self.assertContains(response, 'How published')
        self.assertContains(response, 'How draft')

    def test_admin_can_filter_by_audience(self):
        self._announcement('TEACHERS', published=True, title='Teacher note')
        self._announcement('PARENTS', published=True, title='Parent note')
        self._login(self.admin)
        response = self.client.get(
            reverse('announcements:list'), {'audience': 'PARENTS'}
        )
        self.assertContains(response, 'Parent note')
        self.assertNotContains(response, 'Teacher note')

    def test_admin_can_filter_by_status_draft(self):
        self._announcement('ALL', published=True, title='Goes live')
        self._announcement('ALL', published=False, title='Still draft')
        self._login(self.admin)
        response = self.client.get(
            reverse('announcements:list'), {'status': 'draft'}
        )
        self.assertContains(response, 'Still draft')
        self.assertNotContains(response, 'Goes live')

    def test_admin_can_search_by_title_text(self):
        self._announcement('ALL', published=True, title='Exam timetable')
        self._announcement('ALL', published=True, title='Sports day')
        self._login(self.admin)
        response = self.client.get(
            reverse('announcements:list'), {'q': 'exam'}
        )
        self.assertContains(response, 'Exam timetable')
        self.assertNotContains(response, 'Sports day')

    def test_pagination_paginates_at_twenty_five(self):
        for i in range(26):
            self._announcement('ALL', published=False, title=f'Item {i}')
        self._login(self.admin)
        response = self._list()
        self.assertEqual(response.context['page_obj'].paginator.per_page, 25)
        self.assertContains(response, 'Item 25')
        self.assertNotContains(response, 'Item 0')
        self.assertContains(response, 'Next')


class AnnouncementDetailViewTests(AnnouncementBase):
    def test_admin_can_open_draft(self):
        draft = self._announcement('ALL', published=False, title='Draft only')
        self._login(self.admin)
        response = self._detail(draft.pk)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Draft only')

    def test_teacher_cannot_open_parent_announcement(self):
        parent_only = self._announcement('PARENTS', published=True)
        self._login(self.teacher)
        self.assertEqual(self._detail(parent_only.pk).status_code, 403)

    def test_teacher_cannot_open_out_of_audience_draft(self):
        draft = self._announcement('TEACHERS', published=False)
        self._login(self.teacher)
        self.assertEqual(self._detail(draft.pk).status_code, 403)

    def test_teacher_can_open_their_published_announcement(self):
        teacher_only = self._announcement('TEACHERS', published=True)
        self._login(self.teacher)
        response = self._detail(teacher_only.pk)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, teacher_only.message)

    def test_parent_cannot_open_teacher_announcement(self):
        teacher_only = self._announcement('TEACHERS', published=True)
        self._login(self.parent)
        self.assertEqual(self._detail(teacher_only.pk).status_code, 403)

    def test_anonymous_redirected_from_detail(self):
        published = self._announcement('ALL', published=True)
        response = self._detail(published.pk)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_missing_announcement_returns_404(self):
        self._login(self.admin)
        self.assertEqual(self._detail(999999).status_code, 404)


class AnnouncementMutationBase(AnnouncementBase):
    def _create_post(self, title='New notice', audience='ALL', message='Hello'):
        return self.client.post(reverse('announcements:add'), {
            'title': title, 'message': message, 'audience': audience,
        })


class AnnouncementCreateTests(AnnouncementMutationBase):
    def test_admin_can_create_announcement(self):
        self._login(self.admin)
        response = self._create_post()
        self.assertRedirects(
            response, reverse('announcements:detail',
                              args=[Announcement.objects.get().pk])
        )
        announcement = Announcement.objects.get()
        self.assertEqual(announcement.created_by, self.admin)
        self.assertFalse(announcement.published)

    def test_create_sets_audience_and_message(self):
        self._login(self.admin)
        self._create_post(audience='PARENTS', message='Fee deadline')
        announcement = Announcement.objects.get()
        self.assertEqual(announcement.audience, 'PARENTS')
        self.assertEqual(announcement.message, 'Fee deadline')

    def test_create_validates_required_fields(self):
        self._login(self.admin)
        response = self.client.post(reverse('announcements:add'), {
            'title': '', 'message': '', 'audience': 'ALL',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required.')
        self.assertEqual(Announcement.objects.count(), 0)

    def test_teacher_cannot_create(self):
        self._login(self.teacher)
        response = self._create_post()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Announcement.objects.count(), 0)

    def test_parent_cannot_create(self):
        self._login(self.parent)
        response = self._create_post()
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_from_create(self):
        response = self._create_post()
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
        self.assertEqual(Announcement.objects.count(), 0)


class AnnouncementEditTests(AnnouncementMutationBase):
    def _edit(self, pk, title='Renamed', audience='ALL', message='Updated'):
        return self.client.post(reverse('announcements:edit', args=[pk]), {
            'title': title, 'message': message, 'audience': audience,
        })

    def _published_announcement(self):
        return self._announcement('ALL', published=True, author=self.admin)

    def test_admin_can_edit_an_announcement(self):
        self._login(self.admin)
        announcement = self._published_announcement()
        response = self._edit(announcement.pk)
        self.assertRedirects(response, reverse('announcements:detail',
                                               args=[announcement.pk]))
        announcement.refresh_from_db()
        self.assertEqual(announcement.title, 'Renamed')
        self.assertEqual(announcement.message, 'Updated')

    def test_editing_published_keeps_published_state(self):
        self._login(self.admin)
        announcement = self._published_announcement()
        published_at = announcement.published_at
        self._edit(announcement.pk)
        announcement.refresh_from_db()
        self.assertTrue(announcement.published)
        self.assertEqual(announcement.published_at, published_at)

    def test_editing_keeps_created_by(self):
        self._login(self.admin)
        announcement = self._announcement('ALL', published=False,
                                          author=self.teacher)
        self._edit(announcement.pk)
        announcement.refresh_from_db()
        self.assertEqual(announcement.created_by, self.teacher)

    def test_teacher_cannot_edit(self):
        self._login(self.teacher)
        announcement = self._published_announcement()
        response = self._edit(announcement.pk)
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_edit(self):
        self._login(self.parent)
        announcement = self._published_announcement()
        response = self._edit(announcement.pk)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected_from_edit(self):
        announcement = self._published_announcement()
        response = self._edit(announcement.pk)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)


class AnnouncementPublishTests(AnnouncementBase):
    def _draft(self):
        return self._announcement('ALL', published=False, author=self.admin)

    def test_admin_can_publish_draft(self):
        self._login(self.admin)
        draft = self._draft()
        self.assertIsNone(draft.published_at)
        response = self._post('publish', draft.pk)
        self.assertRedirects(response, reverse('announcements:detail',
                                               args=[draft.pk]))
        draft.refresh_from_db()
        self.assertTrue(draft.published)
        self.assertIsNotNone(draft.published_at)

    def test_publish_is_POST_only(self):
        self._login(self.admin)
        draft = self._draft()
        response = self.client.get(reverse('announcements:publish',
                                           args=[draft.pk]))
        self.assertEqual(response.status_code, 405)
        draft.refresh_from_db()
        self.assertFalse(draft.published)

    def test_republishing_idempotent_sets_price_at_now(self):
        self._login(self.admin)
        published = self._announcement('ALL', published=True)
        previous_at = published.published_at
        response = self._post('publish', published.pk)
        self.assertEqual(response.status_code, 302)
        published.refresh_from_db()
        self.assertTrue(published.published)
        self.assertGreaterEqual(published.published_at, previous_at)

    def test_teacher_cannot_publish(self):
        self._login(self.teacher)
        draft = self._draft()
        response = self._post('publish', draft.pk)
        self.assertEqual(response.status_code, 403)
        draft.refresh_from_db()
        self.assertFalse(draft.published)

    def test_parent_cannot_publish(self):
        self._login(self.parent)
        draft = self._draft()
        response = self._post('publish', draft.pk)
        self.assertEqual(response.status_code, 403)


class AnnouncementUnpublishTests(AnnouncementBase):
    def _published(self):
        return self._announcement('ALL', published=True, author=self.admin)

    def test_admin_can_unpublish_a_published_announcement(self):
        self._login(self.admin)
        announcement = self._published()
        published_at = announcement.published_at
        response = self._post('unpublish', announcement.pk)
        self.assertRedirects(response, reverse('announcements:detail',
                                               args=[announcement.pk]))
        announcement.refresh_from_db()
        self.assertFalse(announcement.published)
        self.assertEqual(announcement.published_at, published_at)
        self.assertEqual(announcement.created_by, self.admin)

    def test_unpublish_preserves_message_and_history(self):
        self._login(self.admin)
        announcement = self._published()
        self._post('unpublish', announcement.pk)
        announcement.refresh_from_db()
        self.assertEqual(announcement.message, 'Something important for everyone.')

    def test_unpublish_is_POST_only(self):
        self._login(self.admin)
        announcement = self._published()
        response = self.client.get(reverse('announcements:unpublish',
                                           args=[announcement.pk]))
        self.assertEqual(response.status_code, 405)
        announcement.refresh_from_db()
        self.assertTrue(announcement.published)

    def test_teacher_cannot_unpublish(self):
        self._login(self.teacher)
        announcement = self._published()
        response = self._post('unpublish', announcement.pk)
        self.assertEqual(response.status_code, 403)

    def test_parent_cannot_unpublish(self):
        self._login(self.parent)
        announcement = self._published()
        response = self._post('unpublish', announcement.pk)
        self.assertEqual(response.status_code, 403)

    def test_unpublishing_draft_does_not_crash(self):
        self._login(self.admin)
        draft = self._announcement('ALL', published=False)
        response = self._post('unpublish', draft.pk)
        self.assertEqual(response.status_code, 302)


class AnnouncementDeleteTests(AnnouncementBase):
    def test_admin_can_delete_draft(self):
        self._login(self.admin)
        draft = self._announcement('ALL', published=False)
        response = self._post('delete', draft.pk)
        self.assertRedirects(response, reverse('announcements:list'))
        self.assertEqual(Announcement.objects.filter(pk=draft.pk).count(), 0)

    def test_admin_cannot_delete_published_announcement(self):
        self._login(self.admin)
        published = self._published()
        response = self._post('delete', published.pk)
        self.assertRedirects(response, reverse('announcements:detail',
                                               args=[published.pk]))
        self.assertTrue(Announcement.objects.filter(pk=published.pk).exists())

    def test_delete_is_POST_only(self):
        self._login(self.admin)
        draft = self._announcement('ALL', published=False)
        response = self.client.get(reverse('announcements:delete', args=[draft.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Announcement.objects.filter(pk=draft.pk).exists())

    def test_teacher_cannot_delete_draft(self):
        self._login(self.teacher)
        draft = self._announcement('ALL', published=False)
        response = self._post('delete', draft.pk)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Announcement.objects.filter(pk=draft.pk).exists())

    def test_can_delete_guard_reflects_publish_state(self):
        draft = self._announcement('ALL', published=False)
        published = self._published()
        self.assertTrue(can_delete_announcement(draft))
        self.assertFalse(can_delete_announcement(published))

    def _published(self):
        return self._announcement('ALL', published=True, author=self.admin)


class AnnouncementServiceTests(AnnouncementBase):
    def test_publish_sets_published_at(self):
        draft = self._announcement('ALL', published=False)
        publish_announcement(draft)
        draft.refresh_from_db()
        self.assertTrue(draft.published)
        self.assertIsNotNone(draft.published_at)

    def test_unpublish_preserves_author_and_date(self):
        published = self._announcement('ALL', published=True, author=self.admin)
        published_at = published.published_at
        unpublish_announcement(published)
        published.refresh_from_db()
        self.assertFalse(published.published)
        self.assertEqual(published.published_at, published_at)
        self.assertEqual(published.created_by, self.admin)