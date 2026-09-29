from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password

from core.models import Teacher
from students.models import Parent

from .services import (
    PARENT_PERSONA,
    TEACHER_PERSONA,
    create_user_account,
    eligible_parent_records,
    eligible_teacher_records,
    link_user_to_persona,
)


def _apply_bootstrap(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, forms.Select):
            widget.attrs.setdefault('class', 'form-select')
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        else:
            widget.attrs.setdefault('class', 'form-control')


class UserCreateForm(forms.Form):
    """Create a TEACHER or PARENT account and link it to an existing,
    unlinked school record. ADMIN is intentionally not selectable."""

    ROLE_CHOICES = [
        ('TEACHER', 'Teacher'),
        ('PARENT', 'Parent'),
    ]

    role = forms.ChoiceField(choices=ROLE_CHOICES, label='Account type')
    username = forms.CharField(max_length=150, label='Username')
    email = forms.EmailField(required=False, label='Email (optional)')
    password1 = forms.CharField(
        widget=forms.PasswordInput(), label='Password'
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(), label='Confirm password'
    )
    teacher = forms.ModelChoiceField(
        queryset=Teacher.objects.none(), required=False, label='Teacher',
        empty_label='— Select an unlinked teacher —',
    )
    parent = forms.ModelChoiceField(
        queryset=Parent.objects.none(), required=False, label='Parent',
        empty_label='— Select an unlinked parent —',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)
        self.fields['teacher'].queryset = eligible_teacher_records()
        self.fields['parent'].queryset = eligible_parent_records()

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if username and User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get('role')
        password1 = cleaned.get('password1', '')
        password2 = cleaned.get('password2', '')
        teacher = cleaned.get('teacher')
        parent = cleaned.get('parent')

        if password1 and password1 != password2:
            self.add_error('password2', 'Passwords do not match.')
        if password1 and password2 and password1 == password2:
            try:
                validate_password(
                    password2,
                    user=User(username=cleaned.get('username') or 'user'),
                )
            except forms.ValidationError as exc:
                self.add_error('password1', exc.messages)

        if role == 'TEACHER':
            # Re-check eligibility at validation time on top of the queryset.
            if teacher is None:
                self.add_error('teacher', 'Select an unlinked teacher record.')
            elif eligible_teacher_records().filter(pk=teacher.pk).exists():
                cleaned['persona'] = TEACHER_PERSONA
                cleaned['record'] = teacher
            else:
                self.add_error(
                    'teacher', 'This teacher is already linked or no longer eligible.'
                )
        elif role == 'PARENT':
            if parent is None:
                self.add_error('parent', 'Select an unlinked parent record.')
            elif eligible_parent_records().filter(pk=parent.pk).exists():
                cleaned['persona'] = PARENT_PERSONA
                cleaned['record'] = parent
            else:
                self.add_error(
                    'parent', 'This parent is already linked or no longer eligible.'
                )
        else:
            self.add_error('role', 'Only Teacher and Parent accounts can be created.')
        return cleaned

    def save(self):
        cleaned = self.cleaned_data
        return create_user_account(
            username=cleaned['username'],
            password=cleaned['password1'],
            role=cleaned['role'],
            record=cleaned['record'],
            email=cleaned.get('email') or '',
        )


class LinkPersonaForm(forms.Form):
    """Link an existing, eligible user to one eligible unlinked record."""

    persona = None

    record = forms.ModelChoiceField(
        queryset=None, label='Record', empty_label='— Select a record —',
    )

    def __init__(self, *args, persona=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.persona = persona
        if persona == TEACHER_PERSONA:
            self.fields['record'].queryset = eligible_teacher_records()
            self.fields['record'].label = 'Teacher'
        elif persona == PARENT_PERSONA:
            self.fields['record'].queryset = eligible_parent_records()
            self.fields['record'].label = 'Parent'
        _apply_bootstrap(self.fields)

    def save(self, user):
        return link_user_to_persona(user, self.persona, self.cleaned_data['record'])


class UnlinkAccountForm(forms.Form):
    """Confirm-only form for POSTing an unlink action."""

    action = forms.CharField(widget=forms.HiddenInput(), initial='unlink')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['action'].widget.attrs.update({'value': 'unlink'})


class UserSetPasswordForm(SetPasswordForm):
    """Admin-initiated password reset for a single account using Django's
    built-in form: validates with the project validators, hashes with
    ``set_password``, never returns or displays the raw password."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class UserPasswordChangeForm(PasswordChangeForm):
    """Self-service password change, bootstrap-wrapped."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)