from typing import cast

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import User
from apps.content.models import ContentPage, NavigationItem, NavigationMenu


class NavigationMenuAPITests(APITestCase):
    def create_test_user(
        self,
        *,
        phone,
        email,
        full_name,
        password="testpass123",
        is_staff=False,
        is_superuser=False,
    ):
        user = User(
            phone=phone,
            email=email,
            full_name=full_name,
            is_active=True,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )
        user.set_password(password)
        user.save()
        return user

    def setUp(self):
        self.admin_user = self.create_test_user(
            phone="+989990000001",
            email="navigation_admin@example.com",
            full_name="Navigation Admin",
            is_staff=True,
            is_superuser=True,
        )

        self.customer = self.create_test_user(
            phone="+989990000002",
            email="navigation_customer@example.com",
            full_name="Navigation Customer",
        )

        self.about_page = ContentPage.objects.create(
            title="About MallByte",
            slug="about-mallbyte",
            page_type=ContentPage.PageTypeChoices.ABOUT,
            content="About MallByte content.",
            status=ContentPage.StatusChoices.PUBLISHED,
            is_featured=True,
        )

        self.header_menu = NavigationMenu.objects.create(
            name="Header Menu",
            slug="header-menu",
            placement=NavigationMenu.PlacementChoices.HEADER,
            is_active=True,
            order=1,
        )

        self.footer_menu = NavigationMenu.objects.create(
            name="Footer Menu",
            slug="footer-menu",
            placement=NavigationMenu.PlacementChoices.FOOTER,
            is_active=True,
            order=2,
        )

        self.inactive_menu = NavigationMenu.objects.create(
            name="Inactive Menu",
            slug="inactive-menu",
            placement=NavigationMenu.PlacementChoices.HELP,
            is_active=False,
            order=3,
        )

        self.home_item = NavigationItem.objects.create(
            menu=self.header_menu,
            label="Home",
            link_url="/",
            is_active=True,
            requires_auth=False,
            order=1,
        )

        self.products_item = NavigationItem.objects.create(
            menu=self.header_menu,
            label="Products",
            link_url="/products/",
            is_active=True,
            requires_auth=False,
            order=2,
        )

        self.account_item = NavigationItem.objects.create(
            menu=self.header_menu,
            label="My Account",
            link_url="/account/",
            is_active=True,
            requires_auth=True,
            order=3,
        )

        self.inactive_item = NavigationItem.objects.create(
            menu=self.header_menu,
            label="Inactive Item",
            link_url="/inactive/",
            is_active=False,
            requires_auth=False,
            order=4,
        )

        self.about_item = NavigationItem.objects.create(
            menu=self.header_menu,
            label="About",
            page=self.about_page,
            is_active=True,
            requires_auth=False,
            order=5,
        )

        self.parent_item = NavigationItem.objects.create(
            menu=self.header_menu,
            label="Help",
            link_url="/help/",
            is_active=True,
            requires_auth=False,
            order=6,
        )

        self.child_item = NavigationItem.objects.create(
            menu=self.header_menu,
            parent=self.parent_item,
            label="FAQ",
            link_url="/faq/",
            is_active=True,
            requires_auth=False,
            order=1,
        )

        self.inactive_child_item = NavigationItem.objects.create(
            menu=self.header_menu,
            parent=self.parent_item,
            label="Inactive Child",
            link_url="/inactive-child/",
            is_active=False,
            requires_auth=False,
            order=2,
        )

        self.footer_item = NavigationItem.objects.create(
            menu=self.footer_menu,
            label="Terms",
            link_url="/terms/",
            is_active=True,
            requires_auth=False,
            order=1,
        )

    def get_api_client(self) -> APIClient:
        return cast(APIClient, self.client)

    def authenticate_admin(self):
        self.get_api_client().force_authenticate(user=self.admin_user)

    def authenticate_customer(self):
        self.get_api_client().force_authenticate(user=self.customer)

    def get_response_items(self, response):
        data = response.json()

        if isinstance(data, dict) and "results" in data:
            return data["results"]

        return data

    def get_ids(self, response):
        return {item["id"] for item in self.get_response_items(response)}

    def get_item_labels(self, menu_data):
        return {item["label"] for item in menu_data["items"]}

    def test_public_only_sees_active_navigation_menus(self):
        url = reverse("navigation-menu-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.header_menu.id, ids)
        self.assertIn(self.footer_menu.id, ids)
        self.assertNotIn(self.inactive_menu.id, ids)

    def test_admin_can_see_inactive_navigation_menus(self):
        self.authenticate_admin()

        url = reverse("navigation-menu-list")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.header_menu.id, ids)
        self.assertIn(self.footer_menu.id, ids)
        self.assertIn(self.inactive_menu.id, ids)

    def test_public_can_filter_navigation_by_placement(self):
        url = reverse("navigation-menu-list")

        response = self.client.get(
            url,
            data={
                "placement": NavigationMenu.PlacementChoices.HEADER,
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        ids = self.get_ids(response)

        self.assertIn(self.header_menu.id, ids)
        self.assertNotIn(self.footer_menu.id, ids)

    def test_public_can_retrieve_active_navigation_menu_by_slug(self):
        url = reverse("navigation-menu-detail", args=[self.header_menu.slug])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["slug"], self.header_menu.slug)

    def test_public_cannot_retrieve_inactive_navigation_menu(self):
        url = reverse("navigation-menu-detail", args=[self.inactive_menu.slug])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_menu_hides_inactive_and_auth_required_items(self):
        url = reverse("navigation-menu-detail", args=[self.header_menu.slug])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        labels = self.get_item_labels(response.json())

        self.assertIn("Home", labels)
        self.assertIn("Products", labels)
        self.assertIn("About", labels)
        self.assertIn("Help", labels)

        self.assertNotIn("My Account", labels)
        self.assertNotIn("Inactive Item", labels)

    def test_authenticated_customer_can_see_auth_required_items(self):
        self.authenticate_customer()

        url = reverse("navigation-menu-detail", args=[self.header_menu.slug])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        labels = self.get_item_labels(response.json())

        self.assertIn("My Account", labels)

    def test_navigation_item_can_resolve_page_url(self):
        url = reverse("navigation-menu-detail", args=[self.header_menu.slug])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        about_item = next(
            item for item in response.json()["items"] if item["label"] == "About"
        )

        self.assertEqual(about_item["url"], "/pages/about-mallbyte/")
        self.assertEqual(about_item["page_slug"], "about-mallbyte")
        self.assertEqual(about_item["page_title"], "About MallByte")

    def test_navigation_returns_nested_children(self):
        url = reverse("navigation-menu-detail", args=[self.header_menu.slug])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        help_item = next(
            item for item in response.json()["items"] if item["label"] == "Help"
        )

        child_labels = {item["label"] for item in help_item["children"]}

        self.assertIn("FAQ", child_labels)
        self.assertNotIn("Inactive Child", child_labels)

    def test_customer_cannot_create_navigation_menu(self):
        self.authenticate_customer()

        url = reverse("navigation-menu-list")

        response = self.client.post(
            url,
            data={
                "name": "Customer Menu",
                "placement": NavigationMenu.PlacementChoices.MOBILE,
                "is_active": True,
                "order": 10,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(NavigationMenu.objects.filter(name="Customer Menu").exists())

    def test_admin_can_create_navigation_menu(self):
        self.authenticate_admin()

        url = reverse("navigation-menu-list")

        response = self.client.post(
            url,
            data={
                "name": "Mobile Menu",
                "placement": NavigationMenu.PlacementChoices.MOBILE,
                "is_active": True,
                "order": 10,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        menu = NavigationMenu.objects.get(name="Mobile Menu")

        self.assertEqual(menu.slug, "mobile-menu")
        self.assertEqual(menu.placement, NavigationMenu.PlacementChoices.MOBILE)