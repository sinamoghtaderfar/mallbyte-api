from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from apps.content.models import Announcement, Banner, ContentPage, FAQItem
from apps.inventory.models import Stock
from apps.orders.models import Order, OrderItem
from apps.payments.models import Payment
from apps.products.models import Product
from apps.returns.models import ReturnRequest
from apps.reviews.models import ProductReview
from apps.support.models import SupportTicket

User = get_user_model()


def money(value):
    value = Decimal(str(value or 0))
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def number(value):
    return value or 0


def percent_change(current, previous):
    current = Decimal(str(current or 0))
    previous = Decimal(str(previous or 0))

    if previous == 0 and current == 0:
        return "0.00"

    if previous == 0:
        return "100.00"

    change = ((current - previous) / previous) * Decimal("100")
    return str(change.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_date_range(*, period="month", start_date=None, end_date=None):
    now = timezone.now()
    current_timezone = timezone.get_current_timezone()

    if start_date and end_date:
        start_at = timezone.make_aware(
            datetime.combine(start_date, time.min),
            current_timezone,
        )
        end_at = timezone.make_aware(
            datetime.combine(end_date, time.max),
            current_timezone,
        )
        return start_at, end_at

    if period == "today":
        start_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_at, now

    if period == "week":
        return now - timedelta(days=7), now

    if period == "month":
        return now - timedelta(days=30), now

    if period == "year":
        return now - timedelta(days=365), now

    return None, None


def get_previous_date_range(start_at, end_at):
    if not start_at or not end_at:
        return None, None

    duration = end_at - start_at
    previous_end = start_at
    previous_start = start_at - duration

    return previous_start, previous_end


def filter_by_date_range(queryset, field_name, start_at, end_at):
    if start_at:
        queryset = queryset.filter(**{f"{field_name}__gte": start_at})

    if end_at:
        queryset = queryset.filter(**{f"{field_name}__lte": end_at})

    return queryset


def count_by_choices(queryset, field_name, choices):
    result = {}

    for value, _label in choices:
        result[value] = queryset.filter(**{field_name: value}).count()

    return result


def values_count(queryset, field_name):
    rows = (
        queryset.values(field_name)
        .annotate(count=Count("id"))
        .order_by(field_name)
    )

    return {
        row[field_name] or "unknown": row["count"]
        for row in rows
    }


def get_sales_summary(start_at, end_at):
    successful_payments = Payment.objects.filter(
        status=Payment.StatusChoices.SUCCESS,
    )
    successful_payments = filter_by_date_range(
        successful_payments,
        "created_at",
        start_at,
        end_at,
    )

    paid_orders = Order.objects.filter(
        payment_status=Order.PaymentStatusChoices.PAID,
    )
    paid_orders = filter_by_date_range(
        paid_orders,
        "created_at",
        start_at,
        end_at,
    )

    total_revenue = successful_payments.aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    orders_count = paid_orders.count()

    average_order_value = (
        total_revenue / orders_count
        if orders_count
        else Decimal("0")
    )

    return {
        "total_revenue": money(total_revenue),
        "paid_orders_count": orders_count,
        "average_order_value": money(average_order_value),
    }


def get_order_summary(start_at, end_at):
    orders = Order.objects.all()
    orders = filter_by_date_range(orders, "created_at", start_at, end_at)

    return {
        "total_orders": orders.count(),
        "by_status": count_by_choices(
            orders,
            "status",
            Order.StatusChoices.choices,
        ),
        "by_payment_status": count_by_choices(
            orders,
            "payment_status",
            Order.PaymentStatusChoices.choices,
        ),
    }


def get_payment_summary(start_at, end_at):
    payments = Payment.objects.all()
    payments = filter_by_date_range(payments, "created_at", start_at, end_at)

    successful_payments = payments.filter(
        status=Payment.StatusChoices.SUCCESS,
    )
    refunded_payments = payments.filter(
        status=Payment.StatusChoices.REFUNDED,
    )
    failed_payments = payments.filter(
        status=Payment.StatusChoices.FAILED,
    )

    return {
        "total_payments": payments.count(),
        "successful_amount": money(
            successful_payments.aggregate(total=Sum("amount"))["total"]
        ),
        "refunded_amount": money(
            refunded_payments.aggregate(total=Sum("amount"))["total"]
        ),
        "failed_payments": failed_payments.count(),
        "by_status": count_by_choices(
            payments,
            "status",
            Payment.StatusChoices.choices,
        ),
        "by_provider": values_count(payments, "provider"),
    }


def get_product_inventory_summary(start_at, end_at):
    products = Product.objects.all()

    new_products = filter_by_date_range(
        products,
        "created_at",
        start_at,
        end_at,
    )

    stock_items = Stock.objects.select_related("product").annotate(
        available_units=F("quantity") - F("reserved_quantity"),
    )

    low_stock_items = stock_items.filter(
        available_units__gt=0,
        available_units__lte=F("low_stock_threshold"),
    )

    out_of_stock_items = stock_items.filter(
        available_units__lte=0,
    )

    stock_totals = stock_items.aggregate(
        total_quantity=Sum("quantity"),
        total_reserved=Sum("reserved_quantity"),
    )

    top_products_qs = OrderItem.objects.filter(
        order__payment_status=Order.PaymentStatusChoices.PAID,
    )
    top_products_qs = filter_by_date_range(
        top_products_qs,
        "order__created_at",
        start_at,
        end_at,
    )

    top_products = (
        top_products_qs.values(
            "product_id",
            "product__name",
        )
        .annotate(
            quantity_sold=Sum("quantity"),
            revenue=Sum("total_price"),
        )
        .order_by("-quantity_sold")[:5]
    )

    return {
        "total_products": products.count(),
        "active_products": products.filter(is_active=True).count(),
        "approved_products": products.filter(
            status=Product.StatusChoices.APPROVED,
        ).count(),
        "featured_products": products.filter(is_featured=True).count(),
        "new_products": new_products.count(),
        "total_stock_quantity": number(stock_totals["total_quantity"]),
        "reserved_stock_quantity": number(stock_totals["total_reserved"]),
        "low_stock_items": low_stock_items.count(),
        "out_of_stock_items": out_of_stock_items.count(),
        "top_products": [
            {
                "product_id": row["product_id"],
                "name": row["product__name"],
                "quantity_sold": number(row["quantity_sold"]),
                "revenue": money(row["revenue"]),
            }
            for row in top_products
        ],
    }


def get_customer_summary(start_at, end_at):
    users = User.objects.all()

    new_users = filter_by_date_range(
        users,
        "date_joined",
        start_at,
        end_at,
    )

    return {
        "total_users": users.count(),
        "active_users": users.filter(is_active=True).count(),
        "customers": users.filter(
            is_staff=False,
            is_superuser=False,
            is_seller=False,
        ).count(),
        "sellers": users.filter(is_seller=True).count(),
        "staff_users": users.filter(is_staff=True).count(),
        "new_users": new_users.count(),
    }


def get_review_summary(start_at, end_at):
    reviews = ProductReview.objects.all()
    reviews = filter_by_date_range(reviews, "created_at", start_at, end_at)

    approved_reviews = reviews.filter(
        status=ProductReview.StatusChoices.APPROVED,
    )

    average_rating = approved_reviews.aggregate(
        average=Avg("rating")
    )["average"] or Decimal("0")

    return {
        "total_reviews": reviews.count(),
        "average_rating": money(average_rating),
        "verified_reviews": reviews.filter(is_verified_purchase=True).count(),
        "by_status": count_by_choices(
            reviews,
            "status",
            ProductReview.StatusChoices.choices,
        ),
    }


def get_support_summary(start_at, end_at):
    tickets = SupportTicket.objects.all()
    tickets = filter_by_date_range(tickets, "created_at", start_at, end_at)

    return {
        "total_tickets": tickets.count(),
        "unassigned_tickets": tickets.filter(assigned_to__isnull=True).count(),
        "urgent_tickets": tickets.filter(
            priority=SupportTicket.PriorityChoices.URGENT,
        ).count(),
        "high_priority_tickets": tickets.filter(
            priority=SupportTicket.PriorityChoices.HIGH,
        ).count(),
        "by_status": count_by_choices(
            tickets,
            "status",
            SupportTicket.StatusChoices.choices,
        ),
        "by_priority": count_by_choices(
            tickets,
            "priority",
            SupportTicket.PriorityChoices.choices,
        ),
        "by_category": count_by_choices(
            tickets,
            "category",
            SupportTicket.CategoryChoices.choices,
        ),
    }


def get_return_summary(start_at, end_at):
    returns = ReturnRequest.objects.all()
    returns = filter_by_date_range(returns, "created_at", start_at, end_at)

    return {
        "total_returns": returns.count(),
        "requested_amount": money(
            returns.aggregate(total=Sum("total_requested_amount"))["total"]
        ),
        "approved_amount": money(
            returns.aggregate(total=Sum("total_approved_amount"))["total"]
        ),
        "by_status": count_by_choices(
            returns,
            "status",
            ReturnRequest.Status.choices,
        ),
        "by_reason": count_by_choices(
            returns,
            "reason",
            ReturnRequest.Reason.choices,
        ),
        "by_resolution": count_by_choices(
            returns,
            "requested_resolution",
            ReturnRequest.RequestedResolution.choices,
        ),
    }


def get_content_summary(start_at, end_at):
    pages = ContentPage.objects.all()
    banners = Banner.objects.all()
    announcements = Announcement.objects.all()
    faqs = FAQItem.objects.all()

    new_pages = filter_by_date_range(pages, "created_at", start_at, end_at)

    return {
        "pages": {
            "total": pages.count(),
            "published": pages.filter(status=ContentPage.StatusChoices.PUBLISHED).count(),
            "draft": pages.filter(status=ContentPage.StatusChoices.DRAFT).count(),
            "archived": pages.filter(status=ContentPage.StatusChoices.ARCHIVED).count(),
            "featured": pages.filter(is_featured=True).count(),
            "new": new_pages.count(),
        },
        "banners": {
            "total": banners.count(),
            "published": banners.filter(status=Banner.StatusChoices.PUBLISHED).count(),
            "draft": banners.filter(status=Banner.StatusChoices.DRAFT).count(),
        },
        "announcements": {
            "total": announcements.count(),
            "published": announcements.filter(
                status=Announcement.StatusChoices.PUBLISHED,
            ).count(),
            "draft": announcements.filter(
                status=Announcement.StatusChoices.DRAFT,
            ).count(),
        },
        "faqs": {
            "total": faqs.count(),
            "active": faqs.filter(is_active=True).count(),
            "featured": faqs.filter(is_featured=True).count(),
        },
    }


def get_trend_summary(start_at, end_at):
    previous_start_at, previous_end_at = get_previous_date_range(start_at, end_at)

    if not previous_start_at or not previous_end_at:
        return {
            "revenue_change_percent": "0.00",
            "orders_change_percent": "0.00",
            "users_change_percent": "0.00",
        }

    current_sales = get_sales_summary(start_at, end_at)
    previous_sales = get_sales_summary(previous_start_at, previous_end_at)

    current_orders = filter_by_date_range(
        Order.objects.all(),
        "created_at",
        start_at,
        end_at,
    ).count()
    previous_orders = filter_by_date_range(
        Order.objects.all(),
        "created_at",
        previous_start_at,
        previous_end_at,
    ).count()

    current_users = filter_by_date_range(
        User.objects.all(),
        "date_joined",
        start_at,
        end_at,
    ).count()
    previous_users = filter_by_date_range(
        User.objects.all(),
        "date_joined",
        previous_start_at,
        previous_end_at,
    ).count()

    return {
        "revenue_change_percent": percent_change(
            current_sales["total_revenue"],
            previous_sales["total_revenue"],
        ),
        "orders_change_percent": percent_change(
            current_orders,
            previous_orders,
        ),
        "users_change_percent": percent_change(
            current_users,
            previous_users,
        ),
    }


def get_dashboard_analytics(*, period="month", start_date=None, end_date=None):
    start_at, end_at = get_date_range(
        period=period,
        start_date=start_date,
        end_date=end_date,
    )

    return {
        "filters": {
            "period": period,
            "start_at": start_at.isoformat() if start_at else None,
            "end_at": end_at.isoformat() if end_at else None,
        },
        "sales": get_sales_summary(start_at, end_at),
        "orders": get_order_summary(start_at, end_at),
        "payments": get_payment_summary(start_at, end_at),
        "products": get_product_inventory_summary(start_at, end_at),
        "customers": get_customer_summary(start_at, end_at),
        "reviews": get_review_summary(start_at, end_at),
        "support": get_support_summary(start_at, end_at),
        "returns": get_return_summary(start_at, end_at),
        "content": get_content_summary(start_at, end_at),
        "trends": get_trend_summary(start_at, end_at),
    }
    
def get_date_points(start_at, end_at):
    points = []

    current_date = start_at.date()
    end_date = end_at.date()

    while current_date <= end_date:
        points.append(current_date)
        current_date += timedelta(days=1)

    return points


def get_analytics_timeseries(*, period="month", start_date=None, end_date=None):
    start_at, end_at = get_date_range(
        period=period,
        start_date=start_date,
        end_date=end_date,
    )

    if not start_at or not end_at:
        start_at = timezone.now() - timedelta(days=30)
        end_at = timezone.now()

    payments = Payment.objects.filter(
        status=Payment.StatusChoices.SUCCESS,
    )
    payments = filter_by_date_range(
        payments,
        "created_at",
        start_at,
        end_at,
    )

    payment_rows = (
        payments.annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(
            revenue=Sum("amount"),
            successful_payments_count=Count("id"),
        )
        .order_by("date")
    )

    payment_map = {
        row["date"]: {
            "revenue": row["revenue"] or Decimal("0"),
            "successful_payments_count": row["successful_payments_count"] or 0,
        }
        for row in payment_rows
    }

    orders = Order.objects.all()
    orders = filter_by_date_range(
        orders,
        "created_at",
        start_at,
        end_at,
    )

    order_rows = (
        orders.annotate(date=TruncDate("created_at"))
        .values("date")
        .annotate(
            orders_count=Count("id"),
            paid_orders_count=Count(
                "id",
                filter=Q(payment_status=Order.PaymentStatusChoices.PAID),
            ),
        )
        .order_by("date")
    )

    order_map = {
        row["date"]: {
            "orders_count": row["orders_count"] or 0,
            "paid_orders_count": row["paid_orders_count"] or 0,
        }
        for row in order_rows
    }

    users = User.objects.all()
    users = filter_by_date_range(
        users,
        "date_joined",
        start_at,
        end_at,
    )

    user_rows = (
        users.annotate(date=TruncDate("date_joined"))
        .values("date")
        .annotate(
            new_users_count=Count("id"),
        )
        .order_by("date")
    )

    user_map = {
        row["date"]: row["new_users_count"] or 0
        for row in user_rows
    }

    points = []

    total_revenue = Decimal("0")
    total_orders = 0
    total_paid_orders = 0
    total_successful_payments = 0
    total_new_users = 0

    for current_date in get_date_points(start_at, end_at):
        payment_data = payment_map.get(
            current_date,
            {
                "revenue": Decimal("0"),
                "successful_payments_count": 0,
            },
        )

        order_data = order_map.get(
            current_date,
            {
                "orders_count": 0,
                "paid_orders_count": 0,
            },
        )

        revenue = payment_data["revenue"]
        orders_count = order_data["orders_count"]
        paid_orders_count = order_data["paid_orders_count"]
        successful_payments_count = payment_data["successful_payments_count"]
        new_users_count = user_map.get(current_date, 0)

        total_revenue += revenue
        total_orders += orders_count
        total_paid_orders += paid_orders_count
        total_successful_payments += successful_payments_count
        total_new_users += new_users_count

        points.append(
            {
                "date": current_date.isoformat(),
                "revenue": money(revenue),
                "orders_count": orders_count,
                "paid_orders_count": paid_orders_count,
                "successful_payments_count": successful_payments_count,
                "new_users_count": new_users_count,
            }
        )

    return {
        "filters": {
            "period": period,
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
        },
        "totals": {
            "revenue": money(total_revenue),
            "orders_count": total_orders,
            "paid_orders_count": total_paid_orders,
            "successful_payments_count": total_successful_payments,
            "new_users_count": total_new_users,
        },
        "points": points,
    }
    
def get_order_status_breakdown(start_at, end_at):
    orders = Order.objects.all()
    orders = filter_by_date_range(orders, "created_at", start_at, end_at)

    return [
        {
            "status": value,
            "label": label,
            "count": orders.filter(status=value).count(),
        }
        for value, label in Order.StatusChoices.choices
    ]


def get_payment_provider_breakdown(start_at, end_at):
    payments = Payment.objects.all()
    payments = filter_by_date_range(payments, "created_at", start_at, end_at)

    rows = (
        payments.values("provider")
        .annotate(
            count=Count("id"),
            total_amount=Sum("amount"),
            success_count=Count(
                "id",
                filter=Q(status=Payment.StatusChoices.SUCCESS),
            ),
        )
        .order_by("-count")
    )

    return [
        {
            "provider": row["provider"] or "unknown",
            "count": row["count"] or 0,
            "success_count": row["success_count"] or 0,
            "total_amount": money(row["total_amount"]),
        }
        for row in rows
    ]


def get_revenue_by_category_breakdown(start_at, end_at, limit=10):
    order_items = OrderItem.objects.filter(
        order__payment_status=Order.PaymentStatusChoices.PAID,
    )

    order_items = filter_by_date_range(
        order_items,
        "order__created_at",
        start_at,
        end_at,
    )

    rows = (
        order_items.values(
            "product__category_id",
            "product__category__name",
        )
        .annotate(
            revenue=Sum("total_price"),
            quantity_sold=Sum("quantity"),
            orders_count=Count("order", distinct=True),
        )
        .order_by("-revenue")[:limit]
    )

    return [
        {
            "category_id": row["product__category_id"],
            "category_name": row["product__category__name"] or "Unknown",
            "revenue": money(row["revenue"]),
            "quantity_sold": number(row["quantity_sold"]),
            "orders_count": number(row["orders_count"]),
        }
        for row in rows
    ]


def get_top_selling_products_breakdown(start_at, end_at, limit=10):
    order_items = OrderItem.objects.filter(
        order__payment_status=Order.PaymentStatusChoices.PAID,
    )

    order_items = filter_by_date_range(
        order_items,
        "order__created_at",
        start_at,
        end_at,
    )

    rows = (
        order_items.values(
            "product_id",
            "product__name",
            "product__sku",
            "product__category__name",
        )
        .annotate(
            quantity_sold=Sum("quantity"),
            revenue=Sum("total_price"),
            orders_count=Count("order", distinct=True),
        )
        .order_by("-quantity_sold", "-revenue")[:limit]
    )

    return [
        {
            "product_id": row["product_id"],
            "name": row["product__name"],
            "sku": row["product__sku"],
            "category_name": row["product__category__name"] or "Unknown",
            "quantity_sold": number(row["quantity_sold"]),
            "revenue": money(row["revenue"]),
            "orders_count": number(row["orders_count"]),
        }
        for row in rows
    ]


def get_review_status_breakdown(start_at, end_at):
    reviews = ProductReview.objects.all()
    reviews = filter_by_date_range(reviews, "created_at", start_at, end_at)

    return [
        {
            "status": value,
            "label": label,
            "count": reviews.filter(status=value).count(),
        }
        for value, label in ProductReview.StatusChoices.choices
    ]


def get_support_category_breakdown(start_at, end_at):
    tickets = SupportTicket.objects.all()
    tickets = filter_by_date_range(tickets, "created_at", start_at, end_at)

    return [
        {
            "category": value,
            "label": label,
            "count": tickets.filter(category=value).count(),
            "open_count": tickets.filter(
                category=value,
                status=SupportTicket.StatusChoices.OPEN,
            ).count(),
            "urgent_count": tickets.filter(
                category=value,
                priority=SupportTicket.PriorityChoices.URGENT,
            ).count(),
        }
        for value, label in SupportTicket.CategoryChoices.choices
    ]


def get_return_reason_breakdown(start_at, end_at):
    returns = ReturnRequest.objects.all()
    returns = filter_by_date_range(returns, "created_at", start_at, end_at)

    return [
        {
            "reason": value,
            "label": label,
            "count": returns.filter(reason=value).count(),
            "requested_amount": money(
                returns.filter(reason=value).aggregate(
                    total=Sum("total_requested_amount")
                )["total"]
            ),
            "approved_amount": money(
                returns.filter(reason=value).aggregate(
                    total=Sum("total_approved_amount")
                )["total"]
            ),
        }
        for value, label in ReturnRequest.Reason.choices
    ]


def get_analytics_breakdown(*, period="month", start_date=None, end_date=None, limit=10):
    start_at, end_at = get_date_range(
        period=period,
        start_date=start_date,
        end_date=end_date,
    )

    return {
        "filters": {
            "period": period,
            "start_at": start_at.isoformat() if start_at else None,
            "end_at": end_at.isoformat() if end_at else None,
            "limit": limit,
        },
        "orders_by_status": get_order_status_breakdown(start_at, end_at),
        "payments_by_provider": get_payment_provider_breakdown(start_at, end_at),
        "revenue_by_category": get_revenue_by_category_breakdown(
            start_at,
            end_at,
            limit=limit,
        ),
        "top_selling_products": get_top_selling_products_breakdown(
            start_at,
            end_at,
            limit=limit,
        ),
        "reviews_by_status": get_review_status_breakdown(start_at, end_at),
        "support_by_category": get_support_category_breakdown(start_at, end_at),
        "returns_by_reason": get_return_reason_breakdown(start_at, end_at),
    }

def get_stock_alert_items(queryset):
    return [
        {
            "product_id": stock.product_id,
            "product_name": stock.product.name,
            "sku": stock.product.sku,
            "warehouse_id": stock.warehouse_id,
            "warehouse_name": stock.warehouse.name,
            "quantity": stock.quantity,
            "reserved_quantity": stock.reserved_quantity,
            "available_quantity": stock.available_units,
            "low_stock_threshold": stock.low_stock_threshold,
        }
        for stock in queryset
    ]


def get_analytics_alerts(*, limit=10):
    stock_items = Stock.objects.select_related(
        "product",
        "warehouse",
    ).annotate(
        available_units=F("quantity") - F("reserved_quantity"),
    )

    low_stock_qs = stock_items.filter(
        available_units__gt=0,
        available_units__lte=F("low_stock_threshold"),
    ).order_by(
        "available_units",
        "product__name",
    )

    out_of_stock_qs = stock_items.filter(
        available_units__lte=0,
    ).order_by(
        "product__name",
    )

    pending_payment_orders = Order.objects.filter(
        status=Order.StatusChoices.PENDING_PAYMENT,
    )

    failed_payments = Payment.objects.filter(
        status=Payment.StatusChoices.FAILED,
    )

    pending_reviews = ProductReview.objects.filter(
        status=ProductReview.StatusChoices.PENDING,
    )

    urgent_support_tickets = SupportTicket.objects.filter(
        priority=SupportTicket.PriorityChoices.URGENT,
        status__in=[
            SupportTicket.StatusChoices.OPEN,
            SupportTicket.StatusChoices.PENDING,
        ],
    )

    unassigned_support_tickets = SupportTicket.objects.filter(
        assigned_to__isnull=True,
        status__in=[
            SupportTicket.StatusChoices.OPEN,
            SupportTicket.StatusChoices.PENDING,
        ],
    )

    pending_return_statuses = [
        ReturnRequest.Status.SUBMITTED,
        ReturnRequest.Status.UNDER_REVIEW,
        ReturnRequest.Status.WAITING_FOR_ITEM,
        ReturnRequest.Status.ITEM_RECEIVED,
        ReturnRequest.Status.INSPECTING,
        ReturnRequest.Status.REFUND_PENDING,
    ]

    pending_returns = ReturnRequest.objects.filter(
        status__in=pending_return_statuses,
    )

    draft_pages = ContentPage.objects.filter(
        status=ContentPage.StatusChoices.DRAFT,
    )

    draft_banners = Banner.objects.filter(
        status=Banner.StatusChoices.DRAFT,
    )

    draft_announcements = Announcement.objects.filter(
        status=Announcement.StatusChoices.DRAFT,
    )

    out_of_stock_count = out_of_stock_qs.count()
    low_stock_count = low_stock_qs.count()
    failed_payments_count = failed_payments.count()
    pending_payment_orders_count = pending_payment_orders.count()
    pending_reviews_count = pending_reviews.count()
    urgent_support_tickets_count = urgent_support_tickets.count()
    unassigned_support_tickets_count = unassigned_support_tickets.count()
    pending_returns_count = pending_returns.count()
    draft_content_count = (
        draft_pages.count()
        + draft_banners.count()
        + draft_announcements.count()
    )

    return {
        "generated_at": timezone.now().isoformat(),
        "cards": [
            {
                "key": "out_of_stock_items",
                "label": "Out of stock items",
                "value": out_of_stock_count,
                "severity": "critical" if out_of_stock_count else "ok",
            },
            {
                "key": "low_stock_items",
                "label": "Low stock items",
                "value": low_stock_count,
                "severity": "warning" if low_stock_count else "ok",
            },
            {
                "key": "failed_payments",
                "label": "Failed payments",
                "value": failed_payments_count,
                "severity": "warning" if failed_payments_count else "ok",
            },
            {
                "key": "pending_payment_orders",
                "label": "Pending payment orders",
                "value": pending_payment_orders_count,
                "severity": "warning" if pending_payment_orders_count else "ok",
            },
            {
                "key": "pending_reviews",
                "label": "Pending reviews",
                "value": pending_reviews_count,
                "severity": "info" if pending_reviews_count else "ok",
            },
            {
                "key": "urgent_support_tickets",
                "label": "Urgent support tickets",
                "value": urgent_support_tickets_count,
                "severity": "critical" if urgent_support_tickets_count else "ok",
            },
            {
                "key": "unassigned_support_tickets",
                "label": "Unassigned support tickets",
                "value": unassigned_support_tickets_count,
                "severity": "warning" if unassigned_support_tickets_count else "ok",
            },
            {
                "key": "pending_returns",
                "label": "Pending return requests",
                "value": pending_returns_count,
                "severity": "warning" if pending_returns_count else "ok",
            },
            {
                "key": "draft_content",
                "label": "Draft content",
                "value": draft_content_count,
                "severity": "info" if draft_content_count else "ok",
            },
        ],
        "inventory": {
            "out_of_stock": get_stock_alert_items(out_of_stock_qs[:limit]),
            "low_stock": get_stock_alert_items(low_stock_qs[:limit]),
        },
        "orders": {
            "pending_payment_orders": [
                {
                    "id": order.id,
                    "order_number": order.order_number,
                    "customer_id": order.user_id,
                    "total_amount": money(order.total_amount),
                    "created_at": order.created_at.isoformat(),
                }
                for order in pending_payment_orders.order_by("-created_at")[:limit]
            ],
        },
        "payments": {
            "failed_payments": [
                {
                    "id": payment.id,
                    "payment_number": payment.payment_number,
                    "order_id": payment.order_id,
                    "amount": money(payment.amount),
                    "provider": payment.provider,
                    "failure_reason": payment.failure_reason,
                    "created_at": payment.created_at.isoformat(),
                }
                for payment in failed_payments.order_by("-created_at")[:limit]
            ],
        },
        "reviews": {
            "pending_reviews": [
                {
                    "id": review.id,
                    "product_id": review.product_id,
                    "product_name": review.product.name,
                    "customer_id": review.customer_id,
                    "rating": review.rating,
                    "title": review.title,
                    "created_at": review.created_at.isoformat(),
                }
                for review in pending_reviews.select_related("product").order_by("-created_at")[:limit]
            ],
        },
        "support": {
            "urgent_tickets": [
                {
                    "id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "subject": ticket.subject,
                    "customer_id": ticket.customer_id,
                    "priority": ticket.priority,
                    "status": ticket.status,
                    "created_at": ticket.created_at.isoformat(),
                }
                for ticket in urgent_support_tickets.order_by("-created_at")[:limit]
            ],
            "unassigned_tickets": [
                {
                    "id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "subject": ticket.subject,
                    "customer_id": ticket.customer_id,
                    "priority": ticket.priority,
                    "status": ticket.status,
                    "created_at": ticket.created_at.isoformat(),
                }
                for ticket in unassigned_support_tickets.order_by("-created_at")[:limit]
            ],
        },
        "returns": {
            "pending_returns": [
                {
                    "id": return_request.id,
                    "request_number": return_request.request_number,
                    "customer_id": return_request.customer_id,
                    "order_id": return_request.order_id,
                    "status": return_request.status,
                    "reason": return_request.reason,
                    "requested_amount": money(return_request.total_requested_amount),
                    "created_at": return_request.created_at.isoformat(),
                }
                for return_request in pending_returns.order_by("-created_at")[:limit]
            ],
        },
        "content": {
            "draft_pages": draft_pages.count(),
            "draft_banners": draft_banners.count(),
            "draft_announcements": draft_announcements.count(),
        },
    }
    
def safe_csv_value(value):
    if value is None:
        return ""

    value = str(value)

    if value.startswith(("=", "+", "-", "@")):
        return f"'{value}"

    return value


def build_csv_export_data(*, report, period="month", start_date=None, end_date=None):
    start_at, end_at = get_date_range(
        period=period,
        start_date=start_date,
        end_date=end_date,
    )

    if report == "sales":
        return build_sales_export(start_at, end_at)

    if report == "orders":
        return build_orders_export(start_at, end_at)

    if report == "payments":
        return build_payments_export(start_at, end_at)

    if report == "products":
        return build_products_export()

    if report == "support":
        return build_support_export(start_at, end_at)

    if report == "returns":
        return build_returns_export(start_at, end_at)

    if report == "reviews":
        return build_reviews_export(start_at, end_at)

    return {
        "filename": "analytics_export.csv",
        "headers": [],
        "rows": [],
    }


def build_sales_export(start_at, end_at):
    payments = Payment.objects.select_related(
        "order",
        "user",
    ).filter(
        status=Payment.StatusChoices.SUCCESS,
    )

    payments = filter_by_date_range(
        payments,
        "created_at",
        start_at,
        end_at,
    )

    headers = [
        "payment_number",
        "order_number",
        "customer_id",
        "customer_email",
        "provider",
        "amount",
        "currency",
        "paid_at",
        "created_at",
    ]

    rows = [
        [
            payment.payment_number,
            payment.order.order_number,
            payment.user_id,
            payment.user.email,
            payment.provider,
            money(payment.amount),
            payment.currency,
            payment.paid_at.isoformat() if payment.paid_at else "",
            payment.created_at.isoformat(),
        ]
        for payment in payments.order_by("-created_at")
    ]

    return {
        "filename": "analytics_sales_export.csv",
        "headers": headers,
        "rows": rows,
    }


def build_orders_export(start_at, end_at):
    orders = Order.objects.select_related("user").all()

    orders = filter_by_date_range(
        orders,
        "created_at",
        start_at,
        end_at,
    )

    headers = [
        "order_number",
        "customer_id",
        "customer_email",
        "status",
        "payment_status",
        "subtotal",
        "discount_amount",
        "shipping_cost",
        "tax_amount",
        "total_amount",
        "city",
        "paid_at",
        "cancelled_at",
        "delivered_at",
        "created_at",
    ]

    rows = [
        [
            order.order_number,
            order.user_id,
            order.user.email,
            order.status,
            order.payment_status,
            money(order.subtotal),
            money(order.discount_amount),
            money(order.shipping_cost),
            money(order.tax_amount),
            money(order.total_amount),
            order.city,
            order.paid_at.isoformat() if order.paid_at else "",
            order.cancelled_at.isoformat() if order.cancelled_at else "",
            order.delivered_at.isoformat() if order.delivered_at else "",
            order.created_at.isoformat(),
        ]
        for order in orders.order_by("-created_at")
    ]

    return {
        "filename": "analytics_orders_export.csv",
        "headers": headers,
        "rows": rows,
    }


def build_payments_export(start_at, end_at):
    payments = Payment.objects.select_related(
        "order",
        "user",
    ).all()

    payments = filter_by_date_range(
        payments,
        "created_at",
        start_at,
        end_at,
    )

    headers = [
        "payment_number",
        "order_number",
        "customer_id",
        "customer_email",
        "provider",
        "status",
        "amount",
        "currency",
        "gateway_reference",
        "failure_reason",
        "paid_at",
        "failed_at",
        "cancelled_at",
        "refunded_at",
        "created_at",
    ]

    rows = [
        [
            payment.payment_number,
            payment.order.order_number,
            payment.user_id,
            payment.user.email,
            payment.provider,
            payment.status,
            money(payment.amount),
            payment.currency,
            payment.gateway_reference,
            payment.failure_reason,
            payment.paid_at.isoformat() if payment.paid_at else "",
            payment.failed_at.isoformat() if payment.failed_at else "",
            payment.cancelled_at.isoformat() if payment.cancelled_at else "",
            payment.refunded_at.isoformat() if payment.refunded_at else "",
            payment.created_at.isoformat(),
        ]
        for payment in payments.order_by("-created_at")
    ]

    return {
        "filename": "analytics_payments_export.csv",
        "headers": headers,
        "rows": rows,
    }


def build_products_export():
    products = Product.objects.select_related(
        "category",
        "brand",
        "seller",
    ).annotate(
        total_stock_quantity=Sum("stock_items__quantity"),
        reserved_stock_quantity=Sum("stock_items__reserved_quantity"),
    )

    headers = [
        "product_id",
        "name",
        "sku",
        "category",
        "brand",
        "seller_id",
        "status",
        "is_active",
        "is_featured",
        "price",
        "compare_price",
        "final_price",
        "average_rating",
        "reviews_count",
        "total_stock",
        "reserved_stock",
        "available_stock",
        "created_at",
    ]

    rows = []

    for product in products.order_by("-created_at"):
        total_stock = product.total_stock_quantity or 0
        reserved_stock = product.reserved_stock_quantity or 0
        available_stock = total_stock - reserved_stock

        rows.append(
            [
                product.id,
                product.name,
                product.sku,
                product.category.name if product.category_id else "",
                product.brand.name if product.brand_id else "",
                product.seller_id,
                product.status,
                product.is_active,
                product.is_featured,
                money(product.price),
                money(product.compare_price),
                money(product.final_price),
                product.avrage_rating,
                product.reviews_count,
                total_stock,
                reserved_stock,
                available_stock,
                product.created_at.isoformat(),
            ]
        )

    return {
        "filename": "analytics_products_export.csv",
        "headers": headers,
        "rows": rows,
    }


def build_support_export(start_at, end_at):
    tickets = SupportTicket.objects.select_related(
        "customer",
        "assigned_to",
        "order",
        "product",
        "return_request",
    ).all()

    tickets = filter_by_date_range(
        tickets,
        "created_at",
        start_at,
        end_at,
    )

    headers = [
        "ticket_number",
        "customer_id",
        "customer_email",
        "assigned_to_id",
        "subject",
        "category",
        "priority",
        "status",
        "order_number",
        "product_id",
        "return_request_number",
        "last_message_at",
        "resolved_at",
        "closed_at",
        "created_at",
    ]

    rows = [
        [
            ticket.ticket_number,
            ticket.customer_id,
            ticket.customer.phone,
            ticket.assigned_to_id or "",
            ticket.subject,
            ticket.category,
            ticket.priority,
            ticket.status,
            ticket.order.order_number if ticket.order_id else "",
            ticket.product_id or "",
            ticket.return_request.request_number if ticket.return_request_id else "",
            ticket.last_message_at.isoformat() if ticket.last_message_at else "",
            ticket.resolved_at.isoformat() if ticket.resolved_at else "",
            ticket.closed_at.isoformat() if ticket.closed_at else "",
            ticket.created_at.isoformat(),
        ]
        for ticket in tickets.order_by("-created_at")
    ]

    return {
        "filename": "analytics_support_export.csv",
        "headers": headers,
        "rows": rows,
    }


def build_returns_export(start_at, end_at):
    returns = ReturnRequest.objects.select_related(
        "customer",
        "order",
    ).all()

    returns = filter_by_date_range(
        returns,
        "created_at",
        start_at,
        end_at,
    )

    headers = [
        "request_number",
        "customer_id",
        "customer_email",
        "order_number",
        "status",
        "reason",
        "requested_resolution",
        "refund_method",
        "total_requested_amount",
        "total_approved_amount",
        "reviewed_by_id",
        "reviewed_at",
        "closed_at",
        "created_at",
    ]

    rows = [
        [
            return_request.request_number,
            return_request.customer_id or "",
            return_request.customer.phone if return_request.customer_id else "",
            return_request.order.order_number,
            return_request.status,
            return_request.reason,
            return_request.requested_resolution,
            return_request.refund_method,
            money(return_request.total_requested_amount),
            money(return_request.total_approved_amount),
            return_request.reviewed_by_id or "",
            return_request.reviewed_at.isoformat() if return_request.reviewed_at else "",
            return_request.closed_at.isoformat() if return_request.closed_at else "",
            return_request.created_at.isoformat(),
        ]
        for return_request in returns.order_by("-created_at")
    ]

    return {
        "filename": "analytics_returns_export.csv",
        "headers": headers,
        "rows": rows,
    }


def build_reviews_export(start_at, end_at):
    reviews = ProductReview.objects.select_related(
        "customer",
        "product",
        "approved_by",
    ).all()

    reviews = filter_by_date_range(
        reviews,
        "created_at",
        start_at,
        end_at,
    )

    headers = [
        "review_id",
        "product_id",
        "product_name",
        "customer_id",
        "customer_email",
        "rating",
        "title",
        "status",
        "is_verified_purchase",
        "helpful_count",
        "not_helpful_count",
        "approved_by_id",
        "approved_at",
        "created_at",
    ]

    rows = [
        [
            review.id,
            review.product_id,
            review.product.name,
            review.customer_id,
            review.customer.phone,
            review.rating,
            review.title,
            review.status,
            review.is_verified_purchase,
            review.helpful_count,
            review.not_helpful_count,
            review.approved_by_id or "",
            review.approved_at.isoformat() if review.approved_at else "",
            review.created_at.isoformat(),
        ]
        for review in reviews.order_by("-created_at")
    ]

    return {
        "filename": "analytics_reviews_export.csv",
        "headers": headers,
        "rows": rows,
    }