from django import forms

from apps.core.choices import COUNTIES
from apps.core.mixins import BootstrapFormMixin

from .models import CollectionPoint, FarmApplication, Producer, SlotRule


class ProducerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Producer
        fields = ('name', 'county', 'description')
        labels = {'name': 'Shop or farm name'}
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}


class VerifiedProducerForm(ProducerForm):
    class Meta(ProducerForm.Meta):
        fields = ('name', 'county', 'description', 'organic_cert_no')


class FarmApplicationForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = FarmApplication
        fields = ('farm_name', 'registration_no', 'county', 'description')
        labels = {'description': 'About your farm'}
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}


class CollectionPointForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CollectionPoint
        fields = ('name', 'address', 'county', 'cutoff_hours', 'active')


class SlotRuleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SlotRule
        fields = ('weekday', 'start_time', 'end_time', 'slot_minutes', 'capacity', 'active')
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
            'end_time': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        }

    def clean(self):
        cleaned = super().clean()
        start, end, minutes = cleaned.get('start_time'), cleaned.get('end_time'), cleaned.get('slot_minutes')
        if start and end and end <= start:
            self.add_error('end_time', 'The end time must be after the start time.')
        elif start and end and minutes:
            span = (end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)
            if span < minutes:
                self.add_error('end_time', 'There must be room for at least one slot.')
        return cleaned


class DirectoryFilterForm(BootstrapFormMixin, forms.Form):
    county = forms.ChoiceField(choices=[('', 'All counties')] + COUNTIES, required=False)
