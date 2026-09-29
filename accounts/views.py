from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views import View

from .access import AdminRequiredMixin, get_role
from .forms import (
    LinkPersonaForm,
    UnlinkAccountForm,
    UserCreateForm,
    UserPasswordChangeForm,
    UserSetPasswordForm,
)
from .models import UserProfile
from .services import (
    PARENT_PERSONA,
    TEACHER_PERSONA,
    activate_account,
    deactivate_account,
    link_user_to_persona,
    school_persona_for,
    set_account_password,
    unlink_user,
)


def home(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    return redirect('accounts:dashboard')


@login_required
def dashboard(request):
    role = get_role(request.user)
    return render(request, 'dashboard/dashboard.html', {
        'page_title': 'Dashboard',
        'role_label': {
            None: 'Guest',
            'ADMIN': 'Administrator',
            'TEACHER': 'Teacher',
            'PARENT': 'Parent',
        }.get(role, role),
    })


def _load_user(pk):
    return get_object_or_404(
        User.objects.select_related('profile', 'teacher', 'parent'), pk=pk,
    )


class UserListView(AdminRequiredMixin, View):
    template_name = 'accounts/user_list.html'
    page_title = 'Users & Accounts'

    def get(self, request, *args, **kwargs):
        params = request.GET
        queryset = User.objects.select_related('profile', 'teacher', 'parent')
        if params.get('q'):
            queryset = queryset.filter(
                Q(username__icontains=params['q'])
                | Q(first_name__icontains=params['q'])
                | Q(last_name__icontains=params['q'])
                | Q(email__icontains=params['q'])
                | Q(teacher__first_name__icontains=params['q'])
                | Q(teacher__last_name__icontains=params['q'])
                | Q(parent__first_name__icontains=params['q'])
                | Q(parent__last_name__icontains=params['q'])
            )
        if params.get('role'):
            queryset = queryset.filter(profile__role=params['role'])
        if params.get('active') in ('1', '0'):
            queryset = queryset.filter(is_active=params['active'] == '1')
        linked = params.get('linked')
        if linked == 'linked':
            queryset = queryset.filter(
                Q(teacher__isnull=False) | Q(parent__isnull=False)
            )
        elif linked == 'unlinked':
            queryset = queryset.filter(
                teacher__isnull=True, parent__isnull=True
            )
        paginator = Paginator(queryset.order_by('username'), 25)
        page_obj = paginator.get_page(params.get('page'))
        page_params = params.copy()
        page_params.pop('page', None)
        context = {
            'page_title': self.page_title,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'page_qs': page_params.urlencode(),
            'filters': params,
            'role_options': UserProfile.Roles.choices,
        }
        return render(request, self.template_name, context)


class UserCreateView(AdminRequiredMixin, View):
    template_name = 'accounts/user_form.html'
    page_title = 'Create User Account'

    def get(self, request, *args, **kwargs):
        role = request.GET.get('role')
        initial = None
        if role in (UserProfile.Roles.TEACHER, UserProfile.Roles.PARENT):
            initial = {'role': role}
        form = UserCreateForm(initial=initial)
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
        })

    def post(self, request, *args, **kwargs):
        form = UserCreateForm(request.POST)
        if form.is_valid():
            try:
                user = form.save()
            except ValidationError as exc:
                form.add_error(None, exc.messages)
            else:
                messages.success(
                    request,
                    f'Account "{user.username}" created and linked.',
                )
                return HttpResponseRedirect(
                    reverse('accounts:user_detail', args=[user.pk])
                )
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
        })


class UserDetailView(AdminRequiredMixin, View):
    template_name = 'accounts/user_detail.html'

    def get(self, request, *args, **kwargs):
        user = _load_user(kwargs['pk'])
        persona_kind, record = school_persona_for(user)
        link_form = None
        if not user.is_superuser and not record:
            if user.profile.role == UserProfile.Roles.TEACHER:
                link_form = LinkPersonaForm(persona=TEACHER_PERSONA)
            elif user.profile.role == UserProfile.Roles.PARENT:
                link_form = LinkPersonaForm(persona=PARENT_PERSONA)
        context = {
            'page_title': f'Account — {user.username}',
            'account': user,
            'persona_kind': persona_kind,
            'persona': record,
            'link_form': link_form,
            'is_read_only': user.is_superuser,
        }
        return render(request, self.template_name, context)


class UserPasswordView(AdminRequiredMixin, View):
    template_name = 'accounts/user_password_form.html'
    page_title = 'Reset Password'

    def _guard(self, user):
        if user.is_superuser:
            raise PermissionDenied(
                'Superuser passwords are managed only in Django admin.'
            )

    def get(self, request, *args, **kwargs):
        user = _load_user(kwargs['pk'])
        self._guard(user)
        form = UserSetPasswordForm(user)
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title, 'account': user,
        })

    def post(self, request, *args, **kwargs):
        user = _load_user(kwargs['pk'])
        self._guard(user)
        form = UserSetPasswordForm(user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(
                request, f'Password reset for "{user.username}".'
            )
            return HttpResponseRedirect(
                reverse('accounts:user_detail', args=[user.pk])
            )
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title, 'account': user,
        })


class UserToggleActiveView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        user = _load_user(kwargs['pk'])
        if user.is_superuser:
            raise PermissionDenied(
                'Superuser accounts are read-only in this user interface.'
            )
        try:
            if user.is_active:
                deactivate_account(user)
                messages.success(
                    request, f'Account "{user.username}" deactivated.'
                )
            else:
                activate_account(user)
                messages.success(
                    request, f'Account "{user.username}" activated.'
                )
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        return HttpResponseRedirect(
            reverse('accounts:user_detail', args=[user.pk])
        )


class UserLinkView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        user = _load_user(kwargs['pk'])
        if user.is_superuser:
            raise PermissionDenied(
                'Superuser accounts cannot be linked or unlinked.'
            )
        form = UnlinkAccountForm(request.POST)
        if form.is_valid() and form.cleaned_data['action'] == 'unlink':
            try:
                unlink_user(user)
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
            else:
                messages.success(
                    request, f'Account "{user.username}" unlinked.'
                )
            return HttpResponseRedirect(
                reverse('accounts:user_detail', args=[user.pk])
            )

        persona = None
        if user.profile.role == UserProfile.Roles.TEACHER:
            persona = TEACHER_PERSONA
        elif user.profile.role == UserProfile.Roles.PARENT:
            persona = PARENT_PERSONA
        if persona is None:
            messages.error(
                request, 'This account has no linkable persona.'
            )
            return HttpResponseRedirect(
                reverse('accounts:user_detail', args=[user.pk])
            )
        link_form = LinkPersonaForm(request.POST, persona=persona)
        if link_form.is_valid():
            try:
                link_user_to_persona(user, persona, link_form.cleaned_data['record'])
            except ValidationError as exc:
                messages.error(request, exc.messages[0])
            else:
                messages.success(
                    request, f'Account "{user.username}" linked to a record.'
                )
        else:
            for field_errors in link_form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
        return HttpResponseRedirect(
            reverse('accounts:user_detail', args=[user.pk])
        )


class UserPasswordChangeView(LoginRequiredMixin, auth_views.PasswordChangeView):
    template_name = 'accounts/password_change.html'
    form_class = UserPasswordChangeForm
    success_url = reverse_lazy('accounts:password_change_done')


class UserPasswordChangeDoneView(LoginRequiredMixin, auth_views.PasswordChangeDoneView):
    template_name = 'accounts/password_change_done.html'