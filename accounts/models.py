from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.db import models

from base.models import TimeStampedModel, ActiveModel


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email é obrigatório')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class Tenant(TimeStampedModel, ActiveModel):
    ROLE_CHOICES = [
        ('cartorio', 'Cartório'),
        ('juizado', 'Juizado Especial'),
        ('vara', 'Vara'),
    ]

    name = models.CharField('Nome', max_length=200)
    cnpj = models.CharField('CNPJ', max_length=18, unique=True)
    role = models.CharField('Tipo', max_length=20, choices=ROLE_CHOICES, default='cartorio')
    address = models.TextField('Endereço', blank=True)
    phone = models.CharField('Telefone', max_length=20, blank=True)
    email = models.EmailField('Email', blank=True)

    class Meta:
        verbose_name = 'Tenant'
        verbose_name_plural = 'Tenants'

    def __str__(self):
        return self.name


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    ROLE_CHOICES = [
        ('servidor', 'Servidor'),
        ('administrador', 'Administrador'),
        ('juiz', 'Juiz'),
    ]

    email = models.EmailField('Email', unique=True)
    first_name = models.CharField('Nome', max_length=150)
    last_name = models.CharField('Sobrenome', max_length=150, blank=True)
    role = models.CharField('Perfil', max_length=20, choices=ROLE_CHOICES, default='servidor')
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='users',
        null=True,
        blank=True
    )
    vara = models.CharField('Vara', max_length=200, blank=True)
    comarca = models.CharField('Comarca', max_length=200, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name']

    class Meta:
        verbose_name = 'Usuário'
        verbose_name_plural = 'Usuários'

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    @property
    def tenant_id(self):
        return self.tenant_id if self.tenant else None


class ServerProfile(TimeStampedModel):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile'
    )
    oab = models.CharField('OAB', max_length=20, blank=True)
    specialization = models.CharField('Especialização', max_length=200, blank=True)
    preferences = models.JSONField('Preferências', default=dict)

    class Meta:
        verbose_name = 'Perfil do Servidor'
        verbose_name_plural = 'Perfis dos Servidores'

    def __str__(self):
        return f'Perfil: {self.user.email}'
