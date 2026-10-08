from django import forms


class QuantityForm(forms.Form):
    quantity = forms.IntegerField(min_value=0, max_value=999)


class SlotChoiceForm(forms.Form):
    slot = forms.IntegerField()
