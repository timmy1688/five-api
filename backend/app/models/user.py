from tortoise import fields
from tortoise.models import Model


class User(Model):
    id = fields.IntField(pk=True)
    username = fields.CharField(max_length=64, unique=True)
    hashed_password = fields.CharField(max_length=255)
    role = fields.CharField(max_length=24, default="tenant", source_field="role_code")
    tenant = fields.OneToOneField("models.Tenant", related_name="account", null=True)
    must_change_password = fields.BooleanField(default=False)
    is_active = fields.BooleanField(default=True)
    # Bumped on password change; tokens carrying an older value are rejected.
    token_version = fields.IntField(default=0)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "admins"
