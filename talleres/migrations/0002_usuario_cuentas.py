"""Evolución aditiva: conserva participantes, _id e inscripciones existentes."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("talleres", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # db_table sigue siendo participantes: RenameModel no traslada documentos.
        migrations.RenameModel(old_name="Participante", new_name="Usuario"),
        migrations.AlterModelOptions(name="usuario", options={"ordering": ["nombre", "id"]}),
        migrations.AlterField(
            model_name="usuario", name="codigo",
            field=models.CharField(max_length=32, unique=True, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="usuario", name="ci",
            field=models.CharField(max_length=20, unique=True, null=True, blank=True),
        ),
        migrations.AddField(
            model_name="usuario", name="cuenta",
            field=models.OneToOneField(
                to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT,
                related_name="perfil", null=True, blank=True,
            ),
        ),
        migrations.AddField(
            model_name="usuario", name="rol",
            field=models.CharField(max_length=20, default="participante", choices=[
                ("participante", "Participante"), ("instructor", "Instructor"),
                ("administrador", "Administrador del sistema"),
            ]),
        ),
        migrations.AddField(
            model_name="taller", name="instructor",
            field=models.ForeignKey(
                to="talleres.usuario", on_delete=django.db.models.deletion.PROTECT,
                related_name="talleres_propios", null=True, blank=True,
                limit_choices_to={"rol": "instructor"},
            ),
        ),
        migrations.AlterField(
            model_name="inscripcion", name="participante",
            field=models.ForeignKey(
                to="talleres.usuario", on_delete=django.db.models.deletion.PROTECT,
                related_name="inscripciones", limit_choices_to={"rol": "participante"},
            ),
        ),
    ]
