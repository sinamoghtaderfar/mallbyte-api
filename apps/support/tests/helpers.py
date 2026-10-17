from apps.rbac.models import Role
from apps.rbac.utils import assign_role


def grant_support_agent(user):
    role = Role.objects.get(name="support_agent")

    assign_role(
        user,
        role,
    )

    return user


def grant_support_manager(user):
    role = Role.objects.get(name="support_manager")

    assign_role(
        user,
        role,
    )

    return user
