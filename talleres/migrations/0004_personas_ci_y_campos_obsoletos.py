from django.db import migrations, models


def eliminar_contador_participantes(apps, schema_editor):
    Contador = apps.get_model("talleres", "Contador")
    Contador.objects.using(schema_editor.connection.alias).filter(
        nombre="participantes"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("talleres", "0003_taller_estado_aprobacion")]

    operations = [
        migrations.RemoveField(model_name="usuario", name="codigo"),
        migrations.RemoveField(model_name="taller", name="revision"),
        migrations.AlterField(
            model_name="usuario",
            name="ci",
            field=models.CharField(max_length=20, unique=True),
        ),
        migrations.RunPython(
            eliminar_contador_participantes,
            migrations.RunPython.noop,
        ),
    ]
