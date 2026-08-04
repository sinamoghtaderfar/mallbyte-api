from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def generate_unique_slug(instance, value, slug_field="slug"):
    base_slug = slugify(value) or "content"
    slug = base_slug
    counter = 1

    model_class = instance.__class__

    while model_class.objects.filter(**{slug_field: slug}).exclude(pk=instance.pk).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    return slug


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PublishableModel(models.Model):
    class StatusChoices(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    status = models.CharField(
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.DRAFT,
        db_index=True,
    )

    published_at = models.DateTimeField(null=True, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def is_published(self):
        return self.status == self.StatusChoices.PUBLISHED

    def is_visible_now(self):
        now = timezone.now()

        if self.status != self.StatusChoices.PUBLISHED:
            return False

        if self.starts_at and self.starts_at > now:
            return False

        if self.ends_at and self.ends_at < now:
            return False

        return True

    def publish(self):
        self.status = self.StatusChoices.PUBLISHED

        if not self.published_at:
            self.published_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "published_at",
                "updated_at",
            ]
        )

    def archive(self):
        self.status = self.StatusChoices.ARCHIVED
        self.save(
            update_fields=[
                "status",
                "updated_at",
            ]
        )


class SEOModel(models.Model):
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(max_length=500, blank=True)
    meta_keywords = models.CharField(max_length=500, blank=True)

    class Meta:
        abstract = True


class ContentPage(TimeStampedModel, PublishableModel, SEOModel):
    class PageTypeChoices(models.TextChoices):
        ABOUT = "about", "About"
        TERMS = "terms", "Terms"
        PRIVACY = "privacy", "Privacy"
        HELP = "help", "Help"
        LANDING = "landing", "Landing"
        CUSTOM = "custom", "Custom"

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)

    page_type = models.CharField(
        max_length=30,
        choices=PageTypeChoices.choices,
        default=PageTypeChoices.CUSTOM,
        db_index=True,
    )

    excerpt = models.TextField(blank=True)
    content = models.TextField()

    is_featured = models.BooleanField(default=False, db_index=True)
    order = models.PositiveIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_content_pages",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_content_pages",
    )

    class Meta:
        verbose_name = "Content Page"
        verbose_name_plural = "Content Pages"
        ordering = ["order", "title"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["status", "page_type"]),
            models.Index(fields=["is_featured", "status"]),
            models.Index(fields=["published_at"]),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(self, self.title)

        super().save(*args, **kwargs)


class Banner(TimeStampedModel, PublishableModel):
    class PlacementChoices(models.TextChoices):
        HOME_HERO = "home_hero", "Home Hero"
        HOME_TOP = "home_top", "Home Top"
        HOME_MIDDLE = "home_middle", "Home Middle"
        CATEGORY_TOP = "category_top", "Category Top"
        PRODUCT_DETAIL = "product_detail", "Product Detail"
        CHECKOUT = "checkout", "Checkout"
        GLOBAL = "global", "Global"

    title = models.CharField(max_length=255)
    subtitle = models.TextField(blank=True)

    image = models.ImageField(upload_to="content/banners/")
    mobile_image = models.ImageField(
        upload_to="content/banners/mobile/",
        null=True,
        blank=True,
    )

    placement = models.CharField(
        max_length=40,
        choices=PlacementChoices.choices,
        default=PlacementChoices.HOME_HERO,
        db_index=True,
    )

    cta_text = models.CharField(max_length=100, blank=True)
    link_url = models.CharField(max_length=500, blank=True)

    background_color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional UI color, for example: #000000",
    )

    text_color = models.CharField(
        max_length=20,
        blank=True,
        help_text="Optional UI color, for example: #FFFFFF",
    )

    order = models.PositiveIntegerField(default=0)
    is_clickable = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Banner"
        verbose_name_plural = "Banners"
        ordering = ["placement", "order", "-created_at"]
        indexes = [
            models.Index(fields=["placement", "status"]),
            models.Index(fields=["order"]),
            models.Index(fields=["starts_at", "ends_at"]),
        ]

    def __str__(self):
        return f"{self.title} - {self.placement}"


class FAQCategory(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, db_index=True)
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True, db_index=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "FAQ Category"
        verbose_name_plural = "FAQ Categories"
        ordering = ["order", "name"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active", "order"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(self, self.name)

        super().save(*args, **kwargs)


class FAQItem(TimeStampedModel):
    category = models.ForeignKey(
        FAQCategory,
        on_delete=models.CASCADE,
        related_name="items",
    )

    question = models.CharField(max_length=255)
    answer = models.TextField()

    is_active = models.BooleanField(default=True, db_index=True)
    is_featured = models.BooleanField(default=False, db_index=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "FAQ Item"
        verbose_name_plural = "FAQ Items"
        ordering = ["category__order", "order", "question"]
        indexes = [
            models.Index(fields=["category", "is_active"]),
            models.Index(fields=["is_featured", "is_active"]),
            models.Index(fields=["order"]),
        ]

    def __str__(self):
        return self.question


class Announcement(TimeStampedModel, PublishableModel):
    class LevelChoices(models.TextChoices):
        INFO = "info", "Info"
        SUCCESS = "success", "Success"
        WARNING = "warning", "Warning"
        DANGER = "danger", "Danger"

    class PlacementChoices(models.TextChoices):
        GLOBAL = "global", "Global"
        HOME = "home", "Home"
        PRODUCT = "product", "Product"
        CHECKOUT = "checkout", "Checkout"
        ACCOUNT = "account", "Account"

    title = models.CharField(max_length=255)
    message = models.TextField()

    level = models.CharField(
        max_length=20,
        choices=LevelChoices.choices,
        default=LevelChoices.INFO,
        db_index=True,
    )

    placement = models.CharField(
        max_length=30,
        choices=PlacementChoices.choices,
        default=PlacementChoices.GLOBAL,
        db_index=True,
    )

    link_text = models.CharField(max_length=100, blank=True)
    link_url = models.CharField(max_length=500, blank=True)

    is_dismissible = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Announcement"
        verbose_name_plural = "Announcements"
        ordering = ["order", "-created_at"]
        indexes = [
            models.Index(fields=["status", "placement"]),
            models.Index(fields=["level", "status"]),
            models.Index(fields=["starts_at", "ends_at"]),
        ]

    def __str__(self):
        return self.title
    
class NavigationMenu(TimeStampedModel):
    class PlacementChoices(models.TextChoices):
        HEADER = "header", "Header"
        FOOTER = "footer", "Footer"
        MOBILE = "mobile", "Mobile"
        HELP = "help", "Help"
        ACCOUNT = "account", "Account"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, db_index=True)

    placement = models.CharField(
        max_length=30,
        choices=PlacementChoices.choices,
        default=PlacementChoices.HEADER,
        db_index=True,
    )

    is_active = models.BooleanField(default=True, db_index=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Navigation Menu"
        verbose_name_plural = "Navigation Menus"
        ordering = ["placement", "order", "name"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["placement", "is_active"]),
            models.Index(fields=["order"]),
        ]

    def __str__(self):
        return f"{self.name} - {self.placement}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(self, self.name)

        super().save(*args, **kwargs)


class NavigationItem(TimeStampedModel):
    menu = models.ForeignKey(
        NavigationMenu,
        on_delete=models.CASCADE,
        related_name="items",
    )

    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    page = models.ForeignKey(
        ContentPage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="navigation_items",
    )

    label = models.CharField(max_length=120)
    link_url = models.CharField(max_length=500, blank=True)

    icon = models.CharField(
        max_length=80,
        blank=True,
        help_text="Optional icon name for frontend.",
    )

    is_active = models.BooleanField(default=True, db_index=True)
    requires_auth = models.BooleanField(default=False)
    open_in_new_tab = models.BooleanField(default=False)

    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Navigation Item"
        verbose_name_plural = "Navigation Items"
        ordering = ["menu__order", "parent__id", "order", "label"]
        indexes = [
            models.Index(fields=["menu", "is_active"]),
            models.Index(fields=["parent", "order"]),
            models.Index(fields=["page"]),
            models.Index(fields=["order"]),
        ]

    def __str__(self):
        return f"{self.label} - {self.menu.name}"

    @property
    def resolved_url(self):
        if self.link_url:
            return self.link_url

        if self.page:
            return f"/pages/{self.page.slug}/"

        return ""