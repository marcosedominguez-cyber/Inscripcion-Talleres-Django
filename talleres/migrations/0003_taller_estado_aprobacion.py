from django.db import migrations, models


def completar_estado_aprobacion_ausente(apps, schema_editor):
    """Marca como pendientes solo los talleres que aún no tienen el campo."""
    Taller = apps.get_model("talleres", "Taller")
    coleccion = schema_editor.connection.get_collection(Taller._meta.db_table)
    coleccion.update_many(
        {"estado_aprobacion": {"$exists": False}},
        {"$set": {"estado_aprobacion": "pendiente"}},
    )


class Migration(migrations.Migration):
    dependencies = [("talleres", "0002_usuario_cuentas")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    completar_estado_aprobacion_ausente,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="taller",
                    name="estado_aprobacion",
                    field=models.CharField(
                        choices=[
                            ("pendiente", "Pendiente"),
                            ("aprobado", "Aprobado"),
                            ("rechazado", "Rechazado"),
                        ],
                        default="pendiente",
                        max_length=20,
                    ),
                ),
            ],
        ),
    ]
