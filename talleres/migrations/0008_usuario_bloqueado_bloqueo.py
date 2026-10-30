"""Bloqueo persistido e historial de episodios, compatible con MongoDB."""

import django.db.models.deletion
import django.utils.timezone
import django_mongodb_backend.fields
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.exceptions import IrreversibleError

LIMITE_CANCELACIONES_CONSECUTIVAS = 3


class CreateOrAdoptBloqueo(migrations.CreateModel):
    """Crea la colección o completa sus índices sin recrearla."""

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.name)
        if not self.allow_migrate_model(schema_editor.connection.alias, model):
            return
        existentes = schema_editor.connection.introspection.table_names()
        if model._meta.db_table in existentes:
            schema_editor._create_model_indexes(model)
        else:
            schema_editor.create_model(model)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        raise IrreversibleError(
            "Esta migración conserva la colección de bloqueos y su historial."
        )


def _inicializar_participantes(collection):
    """Rellena solo el estado ausente y conserva cualquier estado ya decidido."""
    ausente_o_nulo = {
        "$or": [
            {"bloqueado": {"$exists": False}},
            {"bloqueado": None},
        ]
    }
    collection.update_many(
        {
            "$and": [
                ausente_o_nulo,
                {"cancelaciones_consecutivas": {"$gte": LIMITE_CANCELACIONES_CONSECUTIVAS}},
            ]
        },
        {"$set": {"bloqueado": True}},
    )
    collection.update_many(
        ausente_o_nulo,
        {"$set": {"bloqueado": False}},
    )
    return collection.count_documents({"bloqueado": True})


def migrar_bloqueos(apps, schema_editor):
    """Inicializa el estado heredado sin fabricar episodios históricos."""
    _inicializar_participantes(
        schema_editor.connection.get_collection("participantes")
    )


class Migration(migrations.Migration):

    dependencies = [
        ('talleres', '0007_usuario_cancelaciones_consecutivas_cancelacion'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='usuario',
                    name='bloqueado',
                    field=models.BooleanField(default=False, verbose_name='bloqueado'),
                ),
            ],
        ),
        CreateOrAdoptBloqueo(
            name='Bloqueo',
            fields=[
                ('id', django_mongodb_backend.fields.ObjectIdAutoField(primary_key=True, serialize=False)),
                ('motivo', models.CharField(choices=[('cancelaciones_consecutivas', 'Cancelaciones consecutivas'), ('conducta_inapropiada', 'Conducta inapropiada'), ('incumplimiento_normas', 'Incumplimiento de normas'), ('solicitud_participante', 'Solicitud del participante'), ('manual', 'Otro motivo administrativo')], max_length=40)),
                ('fecha_bloqueo', models.DateTimeField(default=django.utils.timezone.now)),
                ('fecha_desbloqueo', models.DateTimeField(blank=True, null=True)),
                ('bloqueado_por', models.ForeignKey(blank=True, db_column='bloqueado_por', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='bloqueos_realizados', to=settings.AUTH_USER_MODEL)),
                ('desbloqueado_por', models.ForeignKey(blank=True, db_column='desbloqueado_por', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='bloqueos_rehabilitados', to=settings.AUTH_USER_MODEL)),
                ('participante', models.ForeignKey(limit_choices_to={'rol': 'participante'}, on_delete=django.db.models.deletion.PROTECT, related_name='bloqueos', to='talleres.usuario')),
            ],
            options={
                'db_table': 'bloqueos',
                'ordering': ['-fecha_bloqueo', '-id'],
                'indexes': [models.Index(fields=['participante', 'fecha_bloqueo'], name='bloqueos_participante_fecha')],
                'constraints': [models.UniqueConstraint(fields=('participante', 'fecha_desbloqueo'), name='bloqueo_abierto_unico', nulls_distinct=False)],
            },
        ),
        migrations.RunPython(
            migrar_bloqueos,
            migrations.RunPython.noop,
        ),
    ]
