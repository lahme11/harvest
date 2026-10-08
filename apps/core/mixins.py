from django.contrib.auth.mixins import UserPassesTestMixin


class BootstrapFormMixin:
    """Adds Bootstrap classes to every widget so templates can render fields plainly."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            kind = getattr(widget, 'input_type', '')
            if kind == 'checkbox':
                css = 'form-check-input'
            elif kind == 'select' or widget.__class__.__name__ in ('Select', 'SelectMultiple'):
                css = 'form-select'
            elif widget.__class__.__name__ in ('CheckboxSelectMultiple', 'RadioSelect'):
                continue
            else:
                css = 'form-control'
            widget.attrs['class'] = f"{widget.attrs.get('class', '')} {css}".strip()


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_staff
