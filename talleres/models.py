"""Datos persistentes del sistema de terminal, almacenados en MongoDB Atlas."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django_mongodb_backend.fields import ObjectIdAutoField


class Usuario(models.Model):
    class Rol(models.TextChoices):
        PARTICIPANTE = "participante", "Participante"
        INSTRUCTOR = "instructor", "Instructor"
        ADMINISTRADOR = "administrador", "Administrador del sistema"

    id = ObjectIdAutoField(primary_key=True)
    # Solo para compatibilidad con registros de terminal anteriores a las cuentas.
    codigo = models.CharField(max_length=32, unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=200)
    ci = models.CharField(max_length=20, unique=True, null=True, blank=True)
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
        self.codigo = (self.codigo.strip() or None) if self.codigo else None
        self.ci = (self.ci.strip() or None) if self.ci else None
        self.nombre = self.nombre.strip()
        errores = {}
        if self.cuenta_id and (not self.ci or not self.ci.isascii() or not self.ci.isdecimal()):
            errores["ci"] = "La CI de una cuenta debe contener solo números."
        if not self.cuenta_id and not self.codigo:
            errores["codigo"] = "Un registro anterior sin cuenta debe conservar su código."
        if not self.nombre:
            errores["nombre"] = "El nombre del usuario es obligatorio."
        if errores:
            raise ValidationError(errores)

    def __str__(self):
        return f"{self.ci or self.codigo or self.pk} - {self.nombre}"


# Compatibilidad de importación: es el mismo modelo, no otra colección.
Participante = Usuario


class Taller(models.Model):
    class Aprobacion(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente"
        APROBADO = "aprobado", "Aprobado"
        RECHAZADO = "rechazado", "Rechazado"

    id = ObjectIdAutoField(primary_key=True)
    codigo = models.CharField(max_length=32, unique=True)
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, default="")
    cupos = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    fecha_inicio = models.DateTimeField()
    fecha_fin = models.DateTimeField()
    revision = models.PositiveIntegerField(default=0, editable=False)
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
        if self.fecha_inicio and self.fecha_fin and self.fecha_fin <= self.fecha_inicio:
            errores["fecha_fin"] = "El fin debe ser posterior al inicio del taller."
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
    """Secuencias compartidas para los códigos visibles P-001 y T-001."""

    id = ObjectIdAutoField(primary_key=True)
    nombre = models.CharField(max_length=32, unique=True)
    valor = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "contadores"
