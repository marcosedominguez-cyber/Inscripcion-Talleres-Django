"""Modelos persistentes de la aplicación web en MongoDB."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django_mongodb_backend.fields import ObjectIdAutoField

from talleres.reglas import CUPO_MAXIMO, CUPO_MINIMO, error_duracion


class Usuario(models.Model):
    class Rol(models.TextChoices):
        PARTICIPANTE = "participante", "Participante"
        INSTRUCTOR = "instructor", "Instructor"
        ADMINISTRADOR = "administrador", "Administrador del sistema"

    id = ObjectIdAutoField(primary_key=True)
    nombre = models.CharField(max_length=200)
    ci = models.CharField(max_length=20, unique=True)
    cuenta = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="perfil", null=True, blank=True,
    )
    rol = models.CharField(max_length=20, choices=Rol.choices, default=Rol.PARTICIPANTE)

    class Meta:
        db_table = "participantes"
        ordering = ["nombre", "id"]

    def clean(self):
        super().clean()
        self.ci = self.ci.strip() if self.ci else self.ci
        self.nombre = self.nombre.strip()
        errores = {}
        if not self.ci or not self.ci.isascii() or not self.ci.isdecimal():
            errores["ci"] = "La CI debe contener solo números."
        if not self.nombre:
            errores["nombre"] = "El nombre del usuario es obligatorio."
        if errores:
            raise ValidationError(errores)

    def __str__(self):
        return f"{self.ci or self.pk} - {self.nombre}"


class Taller(models.Model):
    class Aprobacion(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        APROBADO = "aprobado", "Aprobado"
        RECHAZADO = "rechazado", "Rechazado"

    id = ObjectIdAutoField(primary_key=True)
    codigo = models.CharField(max_length=32, unique=True)
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, default="")
    cupos = models.PositiveIntegerField(validators=[
        MinValueValidator(
            CUPO_MINIMO,
            message=f"El cupo debe ser al menos {CUPO_MINIMO}.",
        ),
        MaxValueValidator(
            CUPO_MAXIMO,
            message=f"El cupo no puede superar {CUPO_MAXIMO}.",
        ),
    ])
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()
    instructor = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="talleres_propios",
        null=True, blank=True, limit_choices_to={"rol": Usuario.Rol.INSTRUCTOR},
    )
    # Los registros existentes que no tengan este campo se interpretan como
    # pendientes: no se publican sin una decisión administrativa explícita.
    estado_aprobacion = models.CharField(
        max_length=20, choices=Aprobacion.choices, default=Aprobacion.PENDIENTE
    )

    class Meta:
        db_table = "talleres"
        ordering = ["fecha_inicio", "codigo"]

    @classmethod
    def from_db(cls, db, field_names, values):
        taller = super().from_db(db, field_names, values)
        # MongoDB permite documentos históricos sin el campo nuevo. Tratarlos
        # como pendientes evita publicarlos y los mantiene revisables en admin.
        if taller.estado_aprobacion is None:
            taller.estado_aprobacion = cls.Aprobacion.PENDIENTE
        return taller

    def clean(self):
        super().clean()
        self.codigo = self.codigo.strip()
        self.nombre = self.nombre.strip()
        errores = {}
        if not self.codigo:
            errores["codigo"] = "El código del taller es obligatorio."
        if not self.nombre:
            errores["nombre"] = "El nombre del taller es obligatorio."
        if self.instructor_id and self.instructor.rol != Usuario.Rol.INSTRUCTOR:
            errores["instructor"] = "El propietario del taller debe ser instructor."
        error_fechas = error_duracion(self.fecha_inicio, self.fecha_fin)
        if error_fechas:
            errores["fecha_fin"] = error_fechas
        if errores:
            raise ValidationError(errores)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class Inscripcion(models.Model):
    class Estado(models.TextChoices):
        CONFIRMADA = "confirmada", "Confirmada"

    id = ObjectIdAutoField(primary_key=True)
    participante = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name="inscripciones",
        limit_choices_to={"rol": Usuario.Rol.PARTICIPANTE},
    )
    taller = models.ForeignKey(
        Taller, on_delete=models.PROTECT, related_name="inscripciones"
    )
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.CONFIRMADA
    )
    fecha_solicitud = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inscripciones"
        ordering = ["fecha_solicitud", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["participante", "taller"],
                name="inscripcion_participante_taller_unica",
            )
        ]

    def __str__(self):
        return f"{self.participante_id} -> {self.taller_id} ({self.estado})"


class Contador(models.Model):
    """Secuencias para los códigos visibles de talleres."""

    id = ObjectIdAutoField(primary_key=True)
    nombre = models.CharField(max_length=32, unique=True)
    valor = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "contadores"
