from django import forms

from talleres.reglas import CUPO_MAXIMO, CUPO_MINIMO, error_duracion


class TallerGestionForm(forms.Form):
    nombre = forms.CharField(max_length=200)
    descripcion = forms.CharField(required=False)
    cupos = forms.IntegerField(
        min_value=CUPO_MINIMO,
        max_value=CUPO_MAXIMO,
        error_messages={
            "min_value": f"El cupo debe ser al menos {CUPO_MINIMO}.",
            "max_value": f"El cupo no puede superar {CUPO_MAXIMO}.",
        },
    )
    fecha_inicio = forms.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"])
    fecha_fin = forms.DateTimeField(input_formats=["%Y-%m-%dT%H:%M"])

    def clean(self):
        datos = super().clean()
        error_fechas = error_duracion(
            datos.get("fecha_inicio"), datos.get("fecha_fin")
        )
        if error_fechas:
            self.add_error("fecha_fin", error_fechas)
        return datos
