from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Avg
from django.utils import timezone

from apps.accounts.models import User
from apps.content.models import Announcement, Banner, ContentPage, FAQCategory, FAQItem
from apps.inventory.models import Stock, Warehouse
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Category, Product
from apps.returns.models import ReturnRequest
from apps.reviews.models import ProductReview
from apps.support.models import SupportTicket

DEMO_PASSWORD = "DemoPass123!"


class Command(BaseCommand):
    help = "Seed demo data for analytics dashboard, charts, alerts, and exports."

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()

        admin = self.create_user(
            phone="+989900000001",
            email="demo.admin@mallbyte.local",
            full_name="Demo Admin",
            is_staff=True,
            is_superuser=True,
        )

        seller = self.create_user(
            phone="+989900000002",
            email="demo.seller@mallbyte.local",
            full_name="Demo Seller",
            is_seller=True,
        )

        customer_1 = self.create_user(
            phone="+989900000003",
            email="demo.customer1@mallbyte.local",
            full_name="Demo Customer One",
        )

        customer_2 = self.create_user(
            phone="+989900000004",
            email="demo.customer2@mallbyte.local",
            full_name="Demo Customer Two",
        )

        customer_3 = self.create_user(
            phone="+989900000005",
            email="demo.customer3@mallbyte.local",
            full_name="Demo Customer Three",
        )

        User.objects.filter(pk=customer_2.pk).update(
            date_joined=now - timedelta(days=1)
        )
        User.objects.filter(pk=customer_3.pk).update(
            date_joined=now - timedelta(days=10)
        )

        electronics = self.create_category(
            name="Demo Electronics",
            slug="demo-analytics-electronics",
        )

        accessories = self.create_category(
            name="Demo Accessories",
            slug="demo-analytics-accessories",
        )

        laptop = self.create_product(
            seller=seller,
            category=electronics,
            name="Demo Pro Laptop",
            slug="demo-pro-laptop",
            sku="DEMO-LAPTOP-001",
            price=Decimal("45000000"),
            is_featured=True,
        )

        phone = self.create_product(
            seller=seller,
            category=electronics,
            name="Demo Smart Phone",
            slug="demo-smart-phone",
            sku="DEMO-PHONE-001",
            price=Decimal("25000000"),
            is_featured=True,
        )

        headphones = self.create_product(
            seller=seller,
            category=accessories,
            name="Demo Wireless Headphones",
            slug="demo-wireless-headphones",
            sku="DEMO-HEADPHONE-001",
            price=Decimal("5000000"),
            is_featured=False,
        )

        mouse = self.create_product(
            seller=seller,
            category=accessories,
            name="Demo Gaming Mouse",
            slug="demo-gaming-mouse",
            sku="DEMO-MOUSE-001",
            price=Decimal("2000000"),
            is_featured=False,
        )

        warehouse = self.create_warehouse(admin)

        self.create_stock(
            product=laptop,
            warehouse=warehouse,
            quantity=30,
            reserved_quantity=5,
            low_stock_threshold=10,
            updated_by=admin,
        )

        self.create_stock(
            product=phone,
            warehouse=warehouse,
            quantity=4,
            reserved_quantity=0,
            low_stock_threshold=5,
            updated_by=admin,
        )

        self.create_stock(
            product=headphones,
            warehouse=warehouse,
            quantity=0,
            reserved_quantity=0,
            low_stock_threshold=5,
            updated_by=admin,
        )

        self.create_stock(
            product=mouse,
            warehouse=warehouse,
            quantity=100,
            reserved_quantity=10,
            low_stock_threshold=20,
            updated_by=admin,
        )

        order_today = self.create_order(
            order_number="DEMO-ORD-001",
            user=customer_1,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("70000000"),
            paid_at=now,
            created_at=now,
        )

        self.rebuild_order_items(
            order=order_today,
            warehouse=warehouse,
            items=[
                {
                    "product": laptop,
                    "quantity": 1,
                    "unit_price": Decimal("45000000"),
                },
                {
                    "product": phone,
                    "quantity": 1,
                    "unit_price": Decimal("25000000"),
                },
            ],
        )

        order_yesterday = self.create_order(
            order_number="DEMO-ORD-002",
            user=customer_2,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("15000000"),
            paid_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
        )

        self.rebuild_order_items(
            order=order_yesterday,
            warehouse=warehouse,
            items=[
                {
                    "product": headphones,
                    "quantity": 3,
                    "unit_price": Decimal("5000000"),
                },
            ],
        )

        pending_order = self.create_order(
            order_number="DEMO-ORD-003",
            user=customer_3,
            status_value=Order.StatusChoices.PENDING_PAYMENT,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal=Decimal("4000000"),
            created_at=now,
        )

        self.rebuild_order_items(
            order=pending_order,
            warehouse=warehouse,
            items=[
                {
                    "product": mouse,
                    "quantity": 2,
                    "unit_price": Decimal("2000000"),
                },
            ],
        )

        old_order = self.create_order(
            order_number="DEMO-ORD-004",
            user=customer_1,
            status_value=Order.StatusChoices.PAID,
            payment_status=Order.PaymentStatusChoices.PAID,
            subtotal=Decimal("45000000"),
            paid_at=now - timedelta(days=45),
            created_at=now - timedelta(days=45),
        )

        self.rebuild_order_items(
            order=old_order,
            warehouse=warehouse,
            items=[
                {
                    "product": laptop,
                    "quantity": 1,
                    "unit_price": Decimal("45000000"),
                },
            ],
        )

        cancelled_order = self.create_order(
            order_number="DEMO-ORD-005",
            user=customer_2,
            status_value=Order.StatusChoices.CANCELLED,
            payment_status=Order.PaymentStatusChoices.UNPAID,
            subtotal=Decimal("25000000"),
            cancelled_at=now - timedelta(days=3),
            created_at=now - timedelta(days=3),
        )

        self.rebuild_order_items(
            order=cancelled_order,
            warehouse=warehouse,
            items=[
                {
                    "product": phone,
                    "quantity": 1,
                    "unit_price": Decimal("25000000"),
                },
            ],
        )

        self.create_payment(
            payment_number="DEMO-PAY-001",
            order=order_today,
            user=customer_1,
            provider=Payment.ProviderChoices.MOCK,
            status_value=Payment.StatusChoices.SUCCESS,
            amount=Decimal("70000000"),
            paid_at=now,
            created_at=now,
            created_by=admin,
        )

        self.create_payment(
            payment_number="DEMO-PAY-002",
            order=order_yesterday,
            user=customer_2,
            provider=Payment.ProviderChoices.MOCK,
            status_value=Payment.StatusChoices.SUCCESS,
            amount=Decimal("15000000"),
            paid_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
            created_by=admin,
        )

        self.create_payment(
            payment_number="DEMO-PAY-003",
            order=pending_order,
            user=customer_3,
            provider=Payment.ProviderChoices.STRIPE,
            status_value=Payment.StatusChoices.FAILED,
            amount=Decimal("4000000"),
            failed_at=now,
            failure_reason="Demo failed payment for analytics alerts.",
            created_at=now,
            created_by=admin,
        )

        self.create_payment(
            payment_number="DEMO-PAY-004",
            order=old_order,
            user=customer_1,
            provider=Payment.ProviderChoices.MOCK,
            status_value=Payment.StatusChoices.SUCCESS,
            amount=Decimal("45000000"),
            paid_at=now - timedelta(days=45),
            created_at=now - timedelta(days=45),
            created_by=admin,
        )

        self.create_review(
            customer=customer_1,
            product=laptop,
            rating=5,
            title="Excellent demo laptop",
            comment="This is a demo approved review.",
            status_value=ProductReview.StatusChoices.APPROVED,
            approved_by=admin,
            approved_at=now,
            created_at=now,
        )

        self.create_review(
            customer=customer_2,
            product=phone,
            rating=4,
            title="Pending demo phone review",
            comment="This is a demo pending review for moderation.",
            status_value=ProductReview.StatusChoices.PENDING,
            created_at=now,
        )

        self.create_review(
            customer=customer_3,
            product=headphones,
            rating=3,
            title="Average demo headphones",
            comment="This is another approved review.",
            status_value=ProductReview.StatusChoices.APPROVED,
            approved_by=admin,
            approved_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
        )

        self.update_product_review_stats([laptop, phone, headphones, mouse])

        self.create_support_ticket(
            ticket_number="DEMO-TIC-001",
            customer=customer_1,
            assigned_to=admin,
            subject="Urgent demo order issue",
            category=SupportTicket.CategoryChoices.ORDER,
            priority=SupportTicket.PriorityChoices.URGENT,
            status_value=SupportTicket.StatusChoices.OPEN,
            order=order_today,
            product=laptop,
            created_at=now,
        )

        self.create_support_ticket(
            ticket_number="DEMO-TIC-002",
            customer=customer_2,
            assigned_to=None,
            subject="Unassigned demo payment issue",
            category=SupportTicket.CategoryChoices.PAYMENT,
            priority=SupportTicket.PriorityChoices.HIGH,
            status_value=SupportTicket.StatusChoices.PENDING,
            order=pending_order,
            product=None,
            created_at=now - timedelta(days=1),
        )

        self.create_support_ticket(
            ticket_number="DEMO-TIC-003",
            customer=customer_3,
            assigned_to=admin,
            subject="Resolved demo product question",
            category=SupportTicket.CategoryChoices.PRODUCT,
            priority=SupportTicket.PriorityChoices.NORMAL,
            status_value=SupportTicket.StatusChoices.RESOLVED,
            order=None,
            product=headphones,
            resolved_at=now - timedelta(days=2),
            created_at=now - timedelta(days=5),
        )

        self.create_return_request(
            request_number="DEMO-RET-001",
            customer=customer_1,
            order=order_today,
            status_value=ReturnRequest.Status.SUBMITTED,
            reason=ReturnRequest.Reason.DAMAGED,
            requested_resolution=ReturnRequest.RequestedResolution.REFUND,
            total_requested_amount=Decimal("5000000"),
            total_approved_amount=Decimal("0"),
            created_at=now,
        )

        self.create_return_request(
            request_number="DEMO-RET-002",
            customer=customer_2,
            order=order_yesterday,
            status_value=ReturnRequest.Status.UNDER_REVIEW,
            reason=ReturnRequest.Reason.WRONG_ITEM,
            requested_resolution=ReturnRequest.RequestedResolution.REPLACEMENT,
            total_requested_amount=Decimal("15000000"),
            total_approved_amount=Decimal("0"),
            created_at=now - timedelta(days=1),
        )

        self.create_content(admin)

        self.stdout.write(self.style.SUCCESS("Analytics demo data seeded successfully."))
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Demo login users:"))
        self.stdout.write(f"Admin phone: +989900000001 | password: {DEMO_PASSWORD}")
        self.stdout.write(f"Seller phone: +989900000002 | password: {DEMO_PASSWORD}")
        self.stdout.write(f"Customer phone: +989900000003 | password: {DEMO_PASSWORD}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Try these endpoints:"))
        self.stdout.write("/api/analytics/dashboard/")
        self.stdout.write("/api/analytics/timeseries/")
        self.stdout.write("/api/analytics/breakdown/")
        self.stdout.write("/api/analytics/alerts/")
        self.stdout.write("/api/analytics/export/?report=sales")

    def create_user(
        self,
        *,
        phone,
        email,
        full_name,
        is_staff=False,
        is_superuser=False,
        is_seller=False,
    ):
        user, _created = User.objects.update_or_create(
            phone=phone,
            defaults={
                "email": email,
                "full_name": full_name,
                "is_active": True,
                "is_staff": is_staff,
                "is_superuser": is_superuser,
                "is_seller": is_seller,
            },
        )
        user.set_password(DEMO_PASSWORD)
        user.save()
        return user

    def create_category(self, *, name, slug):
        category, _created = Category.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "is_active": True,
            },
        )
        return category

    def create_product(
        self,
        *,
        seller,
        category,
        name,
        slug,
        sku,
        price,
        is_featured,
    ):
        product, _created = Product.objects.update_or_create(
            sku=sku,
            defaults={
                "seller": seller,
                "category": category,
                "name": name,
                "slug": slug,
                "description": f"{name} created for analytics demo data.",
                "price": price,
                "compare_price": price + Decimal("1000000"),
                "status": Product.StatusChoices.APPROVED,
                "is_active": True,
                "is_featured": is_featured,
            },
        )
        return product

    def create_warehouse(self, admin):
        warehouse, _created = Warehouse.objects.update_or_create(
            code="DEMO-WH-001",
            defaults={
                "name": "Demo Main Warehouse",
                "type": Warehouse.TypeChoices.MAIN,
                "province": "Tehran",
                "city": "Tehran",
                "address": "Demo warehouse address",
                "postal_code": "1234567890",
                "phone": "02100000000",
                "email": "demo.warehouse@mallbyte.local",
                "manager_name": "Demo Warehouse Manager",
                "manager_phone": "09120000000",
                "is_active": True,
                "created_by": admin,
            },
        )
        return warehouse

    def create_stock(
        self,
        *,
        product,
        warehouse,
        quantity,
        reserved_quantity,
        low_stock_threshold,
        updated_by,
    ):
        stock, _created = Stock.objects.update_or_create(
            product=product,
            warehouse=warehouse,
            defaults={
                "quantity": quantity,
                "reserved_quantity": reserved_quantity,
                "low_stock_threshold": low_stock_threshold,
                "updated_by": updated_by,
            },
        )
        return stock

    def create_order(
        self,
        *,
        order_number,
        user,
        status_value,
        payment_status,
        subtotal,
        created_at,
        paid_at=None,
        cancelled_at=None,
        delivered_at=None,
    ):
        order, _created = Order.objects.update_or_create(
            order_number=order_number,
            defaults={
                "user": user,
                "status": status_value,
                "payment_status": payment_status,
                "subtotal": subtotal,
                "discount_amount": Decimal("0"),
                "shipping_cost": Decimal("0"),
                "tax_amount": Decimal("0"),
                "receiver_name": user.full_name,
                "receiver_phone": user.phone,
                "province": "Tehran",
                "city": "Tehran",
                "address": "Demo customer address",
                "postal_code": "1234567890",
                "paid_at": paid_at,
                "cancelled_at": cancelled_at,
                "delivered_at": delivered_at,
            },
        )

        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        return order

    def rebuild_order_items(self, *, order, warehouse, items):
        order.items.all().delete()

        for item in items:
            OrderItem.objects.create(
                order=order,
                product=item["product"],
                warehouse=warehouse,
                product_name=item["product"].name,
                product_sku=item["product"].sku,
                quantity=item["quantity"],
                unit_price=item["unit_price"],
                total_price=item["unit_price"] * item["quantity"],
            )

    def create_payment(
        self,
        *,
        payment_number,
        order,
        user,
        provider,
        status_value,
        amount,
        created_by,
        created_at,
        paid_at=None,
        failed_at=None,
        failure_reason="",
    ):
        payment, _created = Payment.objects.update_or_create(
            payment_number=payment_number,
            defaults={
                "order": order,
                "user": user,
                "provider": provider,
                "status": status_value,
                "amount": amount,
                "currency": "IRR",
                "paid_at": paid_at,
                "failed_at": failed_at,
                "failure_reason": failure_reason,
                "created_by": created_by,
            },
        )

        Payment.objects.filter(pk=payment.pk).update(created_at=created_at)
        return payment

    def create_review(
        self,
        *,
        customer,
        product,
        rating,
        title,
        comment,
        status_value,
        created_at,
        approved_by=None,
        approved_at=None,
    ):
        review, _created = ProductReview.objects.update_or_create(
            customer=customer,
            product=product,
            defaults={
                "rating": rating,
                "title": title,
                "comment": comment,
                "status": status_value,
                "is_verified_purchase": True,
                "approved_by": approved_by,
                "approved_at": approved_at,
            },
        )

        ProductReview.objects.filter(pk=review.pk).update(created_at=created_at)
        return review

    def update_product_review_stats(self, products):
        for product in products:
            approved_reviews = ProductReview.objects.filter(
                product=product,
                status=ProductReview.StatusChoices.APPROVED,
            )

            average_rating = approved_reviews.aggregate(
                average=Avg("rating")
            )["average"] or Decimal("0")

            Product.objects.filter(pk=product.pk).update(
                avrage_rating=average_rating,
                reviews_count=approved_reviews.count(),
            )

    def create_support_ticket(
        self,
        *,
        ticket_number,
        customer,
        assigned_to,
        subject,
        category,
        priority,
        status_value,
        created_at,
        order=None,
        product=None,
        resolved_at=None,
    ):
        ticket, _created = SupportTicket.objects.update_or_create(
            ticket_number=ticket_number,
            defaults={
                "customer": customer,
                "assigned_to": assigned_to,
                "subject": subject,
                "category": category,
                "priority": priority,
                "status": status_value,
                "order": order,
                "product": product,
                "resolved_at": resolved_at,
            },
        )

        SupportTicket.objects.filter(pk=ticket.pk).update(created_at=created_at)
        return ticket

    def create_return_request(
        self,
        *,
        request_number,
        customer,
        order,
        status_value,
        reason,
        requested_resolution,
        total_requested_amount,
        total_approved_amount,
        created_at,
    ):
        return_request, _created = ReturnRequest.objects.update_or_create(
            request_number=request_number,
            defaults={
                "customer": customer,
                "order": order,
                "status": status_value,
                "reason": reason,
                "requested_resolution": requested_resolution,
                "total_requested_amount": total_requested_amount,
                "total_approved_amount": total_approved_amount,
            },
        )

        ReturnRequest.objects.filter(pk=return_request.pk).update(created_at=created_at)
        return return_request

    def create_content(self, admin):
        ContentPage.objects.update_or_create(
            slug="demo-analytics-homepage",
            defaults={
                "title": "Demo Analytics Homepage",
                "page_type": ContentPage.PageTypeChoices.LANDING,
                "excerpt": "Demo page for analytics dashboard.",
                "content": "This page exists to make analytics demo data realistic.",
                "status": ContentPage.StatusChoices.PUBLISHED,
                "published_at": timezone.now(),
                "is_featured": True,
                "created_by": admin,
                "updated_by": admin,
            },
        )

        ContentPage.objects.update_or_create(
            slug="demo-analytics-draft-page",
            defaults={
                "title": "Demo Analytics Draft Page",
                "page_type": ContentPage.PageTypeChoices.CUSTOM,
                "excerpt": "Draft demo content.",
                "content": "This draft page should appear in analytics alerts.",
                "status": ContentPage.StatusChoices.DRAFT,
                "is_featured": False,
                "created_by": admin,
                "updated_by": admin,
            },
        )

        Banner.objects.update_or_create(
            title="Demo Analytics Hero Banner",
            placement=Banner.PlacementChoices.HOME_HERO,
            defaults={
                "subtitle": "Demo banner for analytics data.",
                "image": ContentFile(
                    b"fake-demo-banner-image",
                    name="demo-analytics-banner.jpg",
                ),
                "status": Banner.StatusChoices.PUBLISHED,
                "published_at": timezone.now(),
                "order": 1,
                "is_clickable": True,
            },
        )

        Banner.objects.update_or_create(
            title="Demo Analytics Draft Banner",
            placement=Banner.PlacementChoices.HOME_TOP,
            defaults={
                "subtitle": "Draft banner for alerts.",
                "image": ContentFile(
                    b"fake-demo-draft-banner-image",
                    name="demo-analytics-draft-banner.jpg",
                ),
                "status": Banner.StatusChoices.DRAFT,
                "order": 2,
                "is_clickable": True,
            },
        )

        Announcement.objects.update_or_create(
            title="Demo Analytics Announcement",
            placement=Announcement.PlacementChoices.GLOBAL,
            defaults={
                "message": "This is a published demo announcement.",
                "level": Announcement.LevelChoices.INFO,
                "status": Announcement.StatusChoices.PUBLISHED,
                "published_at": timezone.now(),
                "order": 1,
                "is_dismissible": True,
            },
        )

        Announcement.objects.update_or_create(
            title="Demo Analytics Draft Announcement",
            placement=Announcement.PlacementChoices.HOME,
            defaults={
                "message": "This draft announcement should appear in alerts.",
                "level": Announcement.LevelChoices.WARNING,
                "status": Announcement.StatusChoices.DRAFT,
                "order": 2,
                "is_dismissible": True,
            },
        )

        faq_category, _created = FAQCategory.objects.update_or_create(
            slug="demo-analytics-faq",
            defaults={
                "name": "Demo Analytics FAQ",
                "description": "FAQ category for analytics demo.",
                "is_active": True,
                "order": 1,
            },
        )

        FAQItem.objects.update_or_create(
            category=faq_category,
            question="What is this demo data for?",
            defaults={
                "answer": "It fills analytics dashboards, alerts, breakdowns, and exports with realistic demo records.",
                "is_active": True,
                "is_featured": True,
                "order": 1,
            },
        )