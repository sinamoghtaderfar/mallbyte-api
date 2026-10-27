"""Single filtering rule for public navigation and CMS draft viewers."""
from django.db.models import Q
from django.utils import timezone
from apps.content.permissions import VIEW, content_has


def can_view_unpublished(user):
    return content_has(user, VIEW)


def _published_reference(prefix, now):
    """A linked page must be published and inside its visibility window."""
    return (
        Q(**{f"{prefix}__isnull": True})
        | (
            Q(**{f"{prefix}__status": "published"})
            & (
                Q(**{f"{prefix}__starts_at__isnull": True})
                | Q(**{f"{prefix}__starts_at__lte": now})
            )
            & (
                Q(**{f"{prefix}__ends_at__isnull": True})
                | Q(**{f"{prefix}__ends_at__gte": now})
            )
        )
    )


def visible_nav_items(queryset, user):
    if can_view_unpublished(user):
        return queryset
    now = timezone.now()
    qs = queryset.filter(is_active=True, menu__is_active=True).filter(
        _published_reference("page", now)
    )
    if not user.is_authenticated:
        qs = qs.filter(requires_auth=False)
    # Public navigations are capped at two levels. Never expose a child whose
    # parent is inactive, hidden from guests, or links to an unpublished page.
    parent_visible = (
        Q(parent__is_active=True)
        & _published_reference("parent__page", now)
    )
    if not user.is_authenticated:
        parent_visible &= Q(parent__requires_auth=False)
    return qs.filter(
        Q(parent__isnull=True) | (Q(parent__parent__isnull=True) & parent_visible)
    )
