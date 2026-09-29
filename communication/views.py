from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View

from accounts.access import ADMIN, AdminRequiredMixin, get_role
from .forms import AnnouncementForm
from .models import Announcement
from .services import (
    can_delete_announcement,
    can_view_announcement,
    publish_announcement,
    unpublish_announcement,
    visible_announcements,
)


class AnnouncementListView(LoginRequiredMixin, View):
    template_name = 'communication/announcement_list.html'
    page_title = 'Announcements'

    def get(self, request, *args, **kwargs):
        params = request.GET
        is_admin = get_role(request.user) == ADMIN
        queryset = visible_announcements(request.user)
        if is_admin:
            if params.get('q'):
                queryset = queryset.filter(
                    Q(title__icontains=params['q'])
                    | Q(message__icontains=params['q'])
                )
            if params.get('audience'):
                queryset = queryset.filter(audience=params['audience'])
            status = params.get('status')
            if status == 'draft':
                queryset = queryset.filter(published=False)
            elif status == 'published':
                queryset = queryset.filter(published=True)
        paginator = Paginator(queryset, 25)
        page_obj = paginator.get_page(params.get('page'))
        page_params = params.copy()
        page_params.pop('page', None)
        context = {
            'page_title': self.page_title,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'page_qs': page_params.urlencode(),
            'filters': params,
            'is_admin': is_admin,
            'audience_options': Announcement.Audience.choices,
        }
        return render(request, self.template_name, context)


class AnnouncementDetailView(LoginRequiredMixin, View):
    template_name = 'communication/announcement_detail.html'

    def get(self, request, *args, **kwargs):
        announcement = get_object_or_404(
            Announcement.objects.select_related('created_by'),
            pk=kwargs['pk'],
        )
        if not can_view_announcement(request.user, announcement):
            raise PermissionDenied(
                'You do not have permission to view this announcement.'
            )
        return render(request, self.template_name, {
            'announcement': announcement,
            'page_title': announcement.title,
            'is_admin': get_role(request.user) == ADMIN,
            'can_delete': can_delete_announcement(announcement),
        })


class AnnouncementCreateView(AdminRequiredMixin, View):
    template_name = 'communication/announcement_form.html'
    page_title = 'New Announcement'

    def get(self, request, *args, **kwargs):
        form = AnnouncementForm()
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
        })

    def post(self, request, *args, **kwargs):
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save(commit=False)
            announcement.created_by = request.user
            announcement.save()
            messages.success(request, 'Announcement saved.')
            return HttpResponseRedirect(
                reverse('announcements:detail', args=[announcement.pk])
            )
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
        })


class AnnouncementEditView(AdminRequiredMixin, View):
    template_name = 'communication/announcement_form.html'
    page_title = 'Edit Announcement'

    def _get(self, request, pk):
        return get_object_or_404(Announcement, pk=pk)

    def get(self, request, *args, **kwargs):
        announcement = self._get(request, kwargs['pk'])
        form = AnnouncementForm(instance=announcement)
        return render(request, self.template_name, {
            'form': form,
            'page_title': self.page_title,
            'announcement': announcement,
        })

    def post(self, request, *args, **kwargs):
        announcement = self._get(request, kwargs['pk'])
        form = AnnouncementForm(request.POST, instance=announcement)
        if form.is_valid():
            form.save()
            messages.success(request, 'Announcement updated.')
            return HttpResponseRedirect(
                reverse('announcements:detail', args=[announcement.pk])
            )
        return render(request, self.template_name, {
            'form': form,
            'page_title': self.page_title,
            'announcement': announcement,
        })


class AnnouncementPublishView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        announcement = get_object_or_404(Announcement, pk=kwargs['pk'])
        if announcement.published:
            messages.info(request, 'This announcement is already published.')
        else:
            publish_announcement(announcement)
            messages.success(request, 'Announcement published.')
        return HttpResponseRedirect(
            reverse('announcements:detail', args=[announcement.pk])
        )


class AnnouncementUnpublishView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        announcement = get_object_or_404(Announcement, pk=kwargs['pk'])
        if not announcement.published:
            messages.info(request, 'This announcement is not currently published.')
        else:
            unpublish_announcement(announcement)
            messages.success(
                request,
                'Announcement unpublished. The record is preserved for '
                'the historical log.',
            )
        return HttpResponseRedirect(
            reverse('announcements:detail', args=[announcement.pk])
        )


class AnnouncementDeleteView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        announcement = get_object_or_404(Announcement, pk=kwargs['pk'])
        if announcement.published:
            messages.error(
                request,
                'Published announcements cannot be deleted. Unpublish it '
                'first if it should be retired.',
            )
            return HttpResponseRedirect(
                reverse('announcements:detail', args=[announcement.pk])
            )
        announcement.delete()
        messages.success(request, 'Draft announcement deleted.')
        return HttpResponseRedirect(reverse('announcements:list'))