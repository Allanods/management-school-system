from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views import View

from accounts.access import (
    ADMIN,
    AdminRequiredMixin,
    ParentRequiredMixin,
    get_role,
)
from core.models import ClassStream, Term
from students.models import Parent, Student
from .forms import (
    FeeStructureForm,
    GenerateChargesForm,
    PaymentForm,
    PaymentVoidForm,
    StudentChargeForm,
)
from .models import FeeCharge, FeePayment, StudentCharge, StudentFeeAccount
from .services import (
    annotate_account_totals,
    annotate_class_totals,
    charge_statement,
    ensure_account,
    finance_dashboard_stats,
    generate_charges_for_class,
    parent_children_finance,
    statement_for,
)


class _PageTitleMixin:
    page_title = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.page_title
        return context


def _current_term():
    return Term.objects.filter(is_current=True).first()


class FinanceDashboardView(AdminRequiredMixin, View):
    template_name = 'fees/dashboard.html'
    page_title = 'Finance Dashboard'

    def get(self, request, *args, **kwargs):
        params = request.GET
        term_id = params.get('term')
        if term_id:
            term = get_object_or_404(Term, pk=term_id)
        else:
            term = _current_term()
        class_stream = None
        if params.get('class_stream'):
            class_stream = get_object_or_404(
                ClassStream, pk=params['class_stream']
            )
        if term is None:
            context = {
                'page_title': self.page_title,
                'term': None,
                'no_terms': True,
            }
        else:
            stats = finance_dashboard_stats(term=term, class_stream=class_stream)
            context = {
                'page_title': self.page_title,
                'term': term,
                'stats': stats,
                'filters': params,
                'term_options': Term.objects.select_related('year'),
                'class_stream_options': ClassStream.objects.select_related(
                    'school_class', 'stream'
                ).order_by('school_class__name', 'stream__name'),
            }
        return render(request, self.template_name, context)


class FeeStructureListView(AdminRequiredMixin, View):
    template_name = 'fees/structure_list.html'
    page_title = 'Fee Structures'

    def get(self, request, *args, **kwargs):
        queryset = FeeCharge.objects.select_related(
            'class_stream__school_class', 'class_stream__stream', 'term__year',
        )
        params = request.GET
        if params.get('term'):
            queryset = queryset.filter(term_id=params['term'])
        if params.get('class_stream'):
            queryset = queryset.filter(class_stream_id=params['class_stream'])
        if params.get('is_active'):
            queryset = queryset.filter(is_active=params['is_active'] == '1')
        paginator = Paginator(queryset.order_by(
            'term__name', 'class_stream__school_class__name', 'description'
        ), 25)
        page_obj = paginator.get_page(params.get('page'))
        page_params = params.copy()
        page_params.pop('page', None)
        context = {
            'page_title': self.page_title,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'page_qs': page_params.urlencode(),
            'filters': params,
            'term_options': Term.objects.select_related('year'),
            'class_stream_options': ClassStream.objects.select_related(
                'school_class', 'stream'
            ).order_by('school_class__name', 'stream__name'),
        }
        return render(request, self.template_name, context)


class FeeStructureCreateView(AdminRequiredMixin, View):
    template_name = 'fees/structure_form.html'
    page_title = 'Add Fee Structure'

    def get(self, request, *args, **kwargs):
        form = FeeStructureForm()
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
        })

    def post(self, request, *args, **kwargs):
        form = FeeStructureForm(request.POST)
        if form.is_valid():
            structure = form.save()
            messages.success(
                request,
                f'Fee structure "{structure.description}" created.',
            )
            return HttpResponseRedirect(reverse('fees:structures'))
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
        })


class FeeStructureEditView(AdminRequiredMixin, View):
    template_name = 'fees/structure_form.html'
    page_title = 'Edit Fee Structure'

    def _get(self, request, pk):
        return get_object_or_404(FeeCharge, pk=pk)

    def get(self, request, *args, **kwargs):
        structure = self._get(request, kwargs['pk'])
        form = FeeStructureForm(instance=structure)
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
            'structure': structure,
        })

    def post(self, request, *args, **kwargs):
        structure = self._get(request, kwargs['pk'])
        form = FeeStructureForm(request.POST, instance=structure)
        if form.is_valid():
            form.save()
            messages.success(request, 'Fee structure updated.')
            return HttpResponseRedirect(reverse('fees:structures'))
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
            'structure': structure,
        })


class FeeStructureDeactivateView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        structure = get_object_or_404(FeeCharge, pk=kwargs['pk'])
        if structure.student_charges.exists():
            messages.error(
                request,
                'This structure is used by student charges and cannot be '
                'deactivated. Charges are protected financial records.',
            )
        else:
            structure.is_active = False
            structure.save(update_fields=['is_active'])
            messages.success(request, 'Fee structure deactivated.')
        return HttpResponseRedirect(reverse('fees:structures'))


class StudentAccountListView(AdminRequiredMixin, View):
    template_name = 'fees/account_list.html'
    page_title = 'Student Fee Accounts'

    def get(self, request, *args, **kwargs):
        params = request.GET
        queryset = StudentFeeAccount.objects.select_related(
            'student', 'term', 'student__class_stream__school_class',
            'student__class_stream__stream',
        )
        if params.get('term'):
            queryset = queryset.filter(term_id=params['term'])
        accounts = queryset
        if params.get('class_stream'):
            class_stream = get_object_or_404(ClassStream, pk=params['class_stream'])
            term = None
            if params.get('term'):
                term = get_object_or_404(Term, pk=params['term'])
            accounts = annotate_class_totals(accounts, class_stream, term)
        else:
            accounts = annotate_account_totals(accounts)
        if params.get('q'):
            accounts = accounts.filter(
                Q(student__first_name__icontains=params['q'])
                | Q(student__last_name__icontains=params['q'])
                | Q(student__admission_no__icontains=params['q'])
            )
        if params.get('outstanding') == '1':
            accounts = accounts.exclude(owed=0)
        accounts = accounts.order_by('student__admission_no')
        paginator = Paginator(accounts, 25)
        page_obj = paginator.get_page(params.get('page'))
        page_params = params.copy()
        page_params.pop('page', None)
        context = {
            'page_title': self.page_title,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'page_qs': page_params.urlencode(),
            'filters': params,
            'term_options': Term.objects.select_related('year'),
            'class_stream_options': ClassStream.objects.select_related(
                'school_class', 'stream'
            ).order_by('school_class__name', 'stream__name'),
            'lookup_form': GenerateChargesForm(),
            'current_term': _current_term(),
        }
        return render(request, self.template_name, context)


class AccountLookupView(AdminRequiredMixin, View):
    """Open (or create) the account for a found student and chosen term."""

    def post(self, request, *args, **kwargs):
        term = get_object_or_404(Term, pk=request.POST.get('term'))
        query = (request.POST.get('student_q') or '').strip()
        if not query:
            messages.error(request, 'Type a student name or admission number.')
            return HttpResponseRedirect(reverse('fees:accounts'))
        students = Student.objects.filter(
            Q(admission_no__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
        if students.count() != 1:
            messages.error(
                request,
                'No unique student matched that search. Narrow the search to '
                'one student.',
            )
            return HttpResponseRedirect(reverse('fees:accounts'))
        account = ensure_account(students.first(), term)
        return HttpResponseRedirect(
            reverse('fees:account_detail', args=[account.pk])
        )


class StudentAccountDetailView(AdminRequiredMixin, View):
    template_name = 'fees/account_detail.html'
    page_title = 'Student Fee Account'

    def get(self, request, *args, **kwargs):
        account = get_object_or_404(
            StudentFeeAccount.objects.select_related(
                'student', 'term', 'student__class_stream__school_class',
                'student__class_stream__stream',
            ),
            pk=kwargs['pk'],
        )
        statement = charge_statement(account)
        charges = StudentCharge.objects.filter(
            student=account.student, term=account.term,
        ).select_related('created_by').order_by('date', 'id')
        payments = FeePayment.objects.filter(
            account=account,
        ).select_related('recorded_by', 'voided_by').order_by('-date', '-id')
        paginator = Paginator(charges, 20)
        page_obj = paginator.get_page(request.GET.get('page'))
        payment_paginator = Paginator(payments, 20)
        payment_page_obj = payment_paginator.get_page(
            request.GET.get('ppage')
        )
        context = {
            'page_title': self.page_title,
            'account': account,
            'statement': statement,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'page_qs': request.GET.copy().urlencode(),
            'payment_page_obj': payment_page_obj,
            'payment_is_paginated': payment_page_obj.has_other_pages(),
        }
        return render(request, self.template_name, context)


class ChargeCreateView(AdminRequiredMixin, View):
    template_name = 'fees/charge_form.html'
    page_title = 'Add Student Charge'

    def _account(self, request, kwargs):
        return get_object_or_404(
            StudentFeeAccount.objects.select_related(
                'student', 'term', 'student__class_stream__school_class',
            ),
            pk=kwargs['pk'],
        )

    def get(self, request, *args, **kwargs):
        account = self._account(request, kwargs)
        form = StudentChargeForm()
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title, 'account': account,
        })

    def post(self, request, *args, **kwargs):
        account = self._account(request, kwargs)
        form = StudentChargeForm(request.POST)
        if form.is_valid():
            charge = form.save(commit=False)
            charge.student = account.student
            charge.term = account.term
            charge.created_by = request.user
            charge.save()
            messages.success(
                request,
                f'Charge "{charge.description}" of KSh {charge.amount} added.',
            )
            return HttpResponseRedirect(
                reverse('fees:account_detail', args=[account.pk])
            )
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title, 'account': account,
        })


class ChargeEditView(AdminRequiredMixin, View):
    template_name = 'fees/charge_form.html'
    page_title = 'Edit Student Charge'

    def _charge(self, request, pk):
        charge = get_object_or_404(
            StudentCharge.objects.select_related(
                'student', 'term', 'student__class_stream__school_class',
            ),
            pk=pk,
        )
        return charge

    def _account_of(self, charge):
        account, _ = StudentFeeAccount.objects.get_or_create(
            student=charge.student, term=charge.term
        )
        return account

    def get(self, request, *args, **kwargs):
        charge = self._charge(request, kwargs['pk'])
        form = StudentChargeForm(instance=charge)
        account = self._account_of(charge)
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
            'account': account, 'charge': charge,
        })

    def post(self, request, *args, **kwargs):
        charge = self._charge(request, kwargs['pk'])
        form = StudentChargeForm(request.POST, instance=charge)
        if form.is_valid():
            form.save()
            messages.success(request, 'Charge updated.')
            account = self._account_of(charge)
            return HttpResponseRedirect(
                reverse('fees:account_detail', args=[account.pk])
            )
        account = self._account_of(charge)
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
            'account': account, 'charge': charge,
        })


class PaymentCreateView(AdminRequiredMixin, View):
    template_name = 'fees/payment_form.html'
    page_title = 'Record Payment'

    def _account(self, request, kwargs):
        return get_object_or_404(
            StudentFeeAccount.objects.select_related(
                'student', 'term', 'student__class_stream__school_class',
            ),
            pk=kwargs['pk'],
        )

    def get(self, request, *args, **kwargs):
        account = self._account(request, kwargs)
        form = PaymentForm(account=account)
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title, 'account': account,
        })

    def post(self, request, *args, **kwargs):
        account = self._account(request, kwargs)
        form = PaymentForm(request.POST, account=account)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.account = account
            payment.recorded_by = request.user
            payment.save()
            messages.success(
                request,
                f'Payment of KSh {payment.amount} recorded.',
            )
            return HttpResponseRedirect(
                reverse('fees:account_detail', args=[account.pk])
            )
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title, 'account': account,
        })


class PaymentEditView(AdminRequiredMixin, View):
    template_name = 'fees/payment_form.html'
    page_title = 'Edit Payment'

    def _payment(self, request, pk):
        payment = get_object_or_404(
            FeePayment.objects.select_related(
                'account__student', 'account__student__class_stream',
            ),
            pk=pk,
        )
        return payment

    def _guard(self, payment):
        if payment.voided:
            raise PermissionDenied(
                'Voided payments cannot be edited. Voided records are '
                'preserved for audit purposes.'
            )

    def get(self, request, *args, **kwargs):
        payment = self._payment(request, kwargs['pk'])
        self._guard(payment)
        form = PaymentForm(instance=payment, account=payment.account)
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
            'account': payment.account, 'payment': payment,
        })

    def post(self, request, *args, **kwargs):
        payment = self._payment(request, kwargs['pk'])
        self._guard(payment)
        form = PaymentForm(
            request.POST, instance=payment, account=payment.account
        )
        if form.is_valid():
            form.save()
            messages.success(request, 'Payment updated.')
            return HttpResponseRedirect(
                reverse('fees:account_detail', args=[payment.account_id])
            )
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title,
            'account': payment.account, 'payment': payment,
        })


class PaymentHistoryView(AdminRequiredMixin, View):
    template_name = 'fees/payment_list.html'
    page_title = 'Payment History'

    def get(self, request, *args, **kwargs):
        params = request.GET
        queryset = FeePayment.objects.select_related(
            'account__student', 'account__term',
            'account__student__class_stream__school_class',
            'recorded_by', 'voided_by',
        )
        if params.get('term'):
            queryset = queryset.filter(account__term_id=params['term'])
        if params.get('method'):
            queryset = queryset.filter(method=params['method'])
        if params.get('voided'):
            queryset = queryset.filter(voided=params['voided'] == '1')
        if params.get('q'):
            queryset = queryset.filter(
                Q(account__student__first_name__icontains=params['q'])
                | Q(account__student__last_name__icontains=params['q'])
                | Q(account__student__admission_no__icontains=params['q'])
                | Q(receipt_no__icontains=params['q'])
            )
        if params.get('date_from'):
            queryset = queryset.filter(date__gte=params['date_from'])
        if params.get('date_to'):
            queryset = queryset.filter(date__lte=params['date_to'])
        paginator = Paginator(queryset.order_by('-date', '-id'), 25)
        page_obj = paginator.get_page(params.get('page'))
        page_params = params.copy()
        page_params.pop('page', None)
        context = {
            'page_title': self.page_title,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'page_qs': page_params.urlencode(),
            'filters': params,
            'term_options': Term.objects.select_related('year'),
            'method_options': FeePayment.Method.choices,
        }
        return render(request, self.template_name, context)


class PaymentVoidView(AdminRequiredMixin, View):
    template_name = 'fees/payment_void.html'
    page_title = 'Void Payment'

    def _payment(self, request, pk):
        return get_object_or_404(
            FeePayment.objects.select_related('account__student'), pk=pk
        )

    def get(self, request, *args, **kwargs):
        payment = self._payment(request, kwargs['pk'])
        if payment.voided:
            messages.info(request, 'This payment has already been voided.')
            return HttpResponseRedirect(
                reverse('fees:payment_list')
                + f'?q={payment.account.student.admission_no}'
            )
        form = PaymentVoidForm()
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title, 'payment': payment,
        })

    def post(self, request, *args, **kwargs):
        payment = self._payment(request, kwargs['pk'])
        if payment.voided:
            messages.info(request, 'This payment has already been voided.')
            return HttpResponseRedirect(reverse('fees:payment_list'))
        form = PaymentVoidForm(request.POST)
        if form.is_valid():
            payment.voided = True
            payment.void_reason = form.cleaned_data['void_reason']
            payment.voided_by = request.user
            payment.save(
                update_fields=['voided', 'void_reason', 'voided_by']
            )
            messages.success(
                request,
                f'Payment of KSh {payment.amount} voided and excluded from '
                'totals. The record remains visible in history.',
            )
            return HttpResponseRedirect(reverse('fees:payment_list'))
        return render(request, self.template_name, {
            'form': form, 'page_title': self.page_title, 'payment': payment,
        })


class GenerateChargesView(AdminRequiredMixin, View):
    page_title = 'Generate Student Charges'

    def post(self, request, *args, **kwargs):
        class_stream = get_object_or_404(
            ClassStream, pk=request.POST.get('class_stream')
        )
        term = get_object_or_404(Term, pk=request.POST.get('term'))
        touched = generate_charges_for_class(class_stream, term, request.user)
        messages.success(
            request,
            f'Generated or updated {touched} charge records for '
            f'{class_stream} · {term}.',
        )
        return HttpResponseRedirect(
            reverse('fees:accounts') + f'?term={term.pk}'
        )


class ParentChildrenView(ParentRequiredMixin, View):
    template_name = 'fees/my_children.html'
    page_title = 'Fees — My Children'

    def get(self, request, *args, **kwargs):
        parent = Parent.objects.filter(user=request.user).first()
        children = (
            parent_children_finance(parent)
            if parent
            else Student.objects.none()
        )
        terms = Term.objects.select_related('year').order_by('year__name', 'name')
        context = {
            'page_title': self.page_title,
            'students': children,
            'current_term': _current_term(),
            'term_options': terms,
        }
        return render(request, self.template_name, context)


class ChildFeesView(ParentRequiredMixin, View):
    template_name = 'fees/child_fees.html'
    page_title = 'Student Fee Statement'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        student = get_object_or_404(
            Student.objects.select_related(
                'class_stream__school_class', 'class_stream__stream'
            ),
            pk=kwargs['pk'],
        )
        if not student.parents.filter(user=request.user).exists():
            raise PermissionDenied(
                'You do not have permission to view this student\'s fees.'
            )
        self.student = student
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        params = request.GET
        term = None
        if params.get('term'):
            term = get_object_or_404(Term, pk=params['term'])
        else:
            term = _current_term()
        account = StudentFeeAccount.objects.filter(
            student=self.student, term=term,
        ).first() if term else None
        if account:
            statement = charge_statement(account)
        elif term is not None:
            statement = statement_for(self.student, term)
        else:
            statement = []
        payments = (
            FeePayment.objects.filter(account=account, voided=False)
            .select_related('recorded_by').order_by('-date', '-id')[:10]
            if account else []
        )
        context = {
            'page_title': self.page_title,
            'student': self.student,
            'term': term,
            'account': account,
            'statement': statement,
            'payments': payments,
            'term_options': Term.objects.select_related('year'),
            'filters': params,
        }
        return render(request, self.template_name, context)