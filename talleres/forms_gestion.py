from django import forms


class TallerGestionForm(forms.Form):
    nombre = forms.CharField(max_length=200)
    descripcion = forms.CharField(required=False)
    cupos = forms.IntegerField(min_value=1)
    fecha_inicio = forms.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"])
    fecha_fin = forms.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"])

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get("fecha_inicio"), datos.get("fecha_fin")
        if inicio and fin and fin <= inicio:
            self.add_error("fecha_fin", "El fin debe ser posterior al inicio del taller.")
        return datos
