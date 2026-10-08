import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile

from .models import Order, Product

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['name', 'image', 'price']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise ValidationError('Please enter a product name.')
        return name

    def clean_price(self):
        price = self.cleaned_data['price']
        if price <= 0:
            raise ValidationError('Price must be greater than zero.')
        return price

    def clean_image(self):
        image = self.cleaned_data.get('image')
        # Only a freshly uploaded file is checked; an unchanged stored file is left alone.
        if isinstance(image, UploadedFile) and image.size > MAX_IMAGE_BYTES:
            raise ValidationError('Image is too large (maximum 5 MB).')
        return image


class SignupForm(forms.Form):
    username = forms.CharField(max_length=150, validators=[UnicodeUsernameValidator()])
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is already taken.')
        return username

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        if password:
            candidate = User(username=cleaned.get('username', ''), email=cleaned.get('email', ''))
            try:
                # Uses the AUTH_PASSWORD_VALIDATORS already configured in settings.py
                password_validation.validate_password(password, candidate)
            except ValidationError as exc:
                self.add_error('password', exc)
        return cleaned


class CheckoutForm(forms.Form):
    address = forms.CharField(min_length=10, max_length=500, widget=forms.Textarea)
    mobile = forms.CharField(max_length=15)

    def clean_address(self):
        return self.cleaned_data['address'].strip()

    def clean_mobile(self):
        number = re.sub(r'[\s\-()]', '', self.cleaned_data['mobile'])
        if not re.fullmatch(r'\+?\d{10,14}', number):
            raise ValidationError('Enter a valid mobile number (10 to 14 digits).')
        return number


class PaymentForm(forms.Form):
    payment_method = forms.ChoiceField(choices=Order.PAYMENT_METHODS)


class ReviewForm(forms.Form):
    comment = forms.CharField(max_length=1000, widget=forms.Textarea)
    rating = forms.IntegerField(min_value=1, max_value=5, required=False)

    def clean_comment(self):
        comment = self.cleaned_data['comment'].strip()
        if not comment:
            raise ValidationError('Please write a comment.')
        return comment
