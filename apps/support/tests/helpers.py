from apps.rbac.models import Role
from apps.rbac.utils import assign_role


def grant_support_agent(user):
    role, _ = Role.objects.get_or_create(
        name="support_agent",
        defaults={
            "description": "Support Agent - Can manage customer support tickets",
            "level": 60,
            "is_system_role": True,
        },
    )

    assign_role(
        user,
        role,
    )

    return user
