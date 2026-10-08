from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render

from apps.catalogue import services as catalogue
from apps.core.mixins import BootstrapFormMixin

from . import services
from .models import Report


class ReportForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Report
        fields = ('reason', 'details')
        widgets = {'details': forms.Textarea(attrs={'rows': 4})}


@login_required
def create(request, product_pk):
    product = catalogue.get_live_product(product_pk)
    if product is None:
        raise Http404
    form = ReportForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.file_report(product, request.user, **form.cleaned_data)
        except services.ReportError as error:
            messages.error(request, str(error))
        else:
            messages.success(request, 'Thanks. Our team will review this product.')
        return redirect(product.get_absolute_url())
    return render(request, 'reports/create.html', {'form': form, 'product': product})
