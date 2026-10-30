from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from talleres.models import Usuario


class RegistroForm(forms.Form):
    nombre_usuario = forms.CharField(max_length=150, label="Nombre de usuario")
    ci = forms.RegexField(r"^[0-9]{1,20}$", max_length=20, label="CI",
                         error_messages={"invalid": "La CI debe contener solo números (hasta 20)."})
    contrasena = forms.CharField(strip=False, widget=forms.PasswordInput, label="Contraseña")
    confirmar_contrasena = forms.CharField(strip=False, widget=forms.PasswordInput)
    rol = forms.ChoiceField(choices=[
        (Usuario.Rol.PARTICIPANTE, "Participante"),
        (Usuario.Rol.INSTRUCTOR, "Instructor"),
    ])

    def clean_nombre_usuario(self):
        nombre = self.cleaned_data["nombre_usuario"]
        # Reutilizar las reglas de username de Django, además del índice único.
        campo = get_user_model()._meta.get_field("username")
        campo.clean(nombre, None)
        if get_user_model().objects.filter(username=nombre).exists():
            raise forms.ValidationError("Ese nombre de usuario ya está registrado.")
        return nombre

    def clean_ci(self):
        ci = self.cleaned_data["ci"]
        if Usuario.objects.filter(ci=ci).exists():
            raise forms.ValidationError("Esa CI ya está registrada.")
        return ci

    def clean(self):
        datos = super().clean()
        clave = datos.get("contrasena")
        if clave and datos.get("confirmar_contrasena") and clave != datos["confirmar_contrasena"]:
            self.add_error("confirmar_contrasena", "Las contraseñas no coinciden.")
        if clave:
            cuenta = get_user_model()(username=datos.get("nombre_usuario", ""))
            try:
                validate_password(clave, cuenta)
            except forms.ValidationError as error:
                self.add_error("contrasena", error)
        return datos


class LoginForm(forms.Form):
    ci = forms.RegexField(r"^[0-9]{1,20}$", max_length=20,
                         error_messages={"invalid": "La CI debe contener solo números."})
    contrasena = forms.CharField(strip=False)
    rol = forms.ChoiceField(choices=[
        (Usuario.Rol.PARTICIPANTE, "Participante"),
        (Usuario.Rol.INSTRUCTOR, "Instructor"),
    ])
