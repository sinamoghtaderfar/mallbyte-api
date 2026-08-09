# MallByte API

MallByte API is a modular Django REST Framework backend for a marketplace-style e-commerce platform.

The project is designed as a realistic backend case study: users can authenticate with email OTP, sellers can manage products and stock, customers can place orders and reviews, and admins can operate the platform through role-based access control, analytics, support, content management, and observability tools.

This repository contains the backend API only. A web or mobile frontend can be developed separately and connected to the API through the documented endpoints.

---

## Table of Contents

- [MallByte API](#mallbyte-api)
  - [Table of Contents](#table-of-contents)
  - [Project Overview](#project-overview)
  - [Project Documentation](#project-documentation)
  - [Core Features](#core-features)
    - [Authentication and Accounts](#authentication-and-accounts)
    - [Authorization and Admin Control](#authorization-and-admin-control)
    - [Commerce Modules](#commerce-modules)
    - [Customer Experience Modules](#customer-experience-modules)
    - [Platform Operations](#platform-operations)
  - [Tech Stack](#tech-stack)
  - [Architecture](#architecture)
  - [Project Structure](#project-structure)
  - [Getting Started with Docker](#getting-started-with-docker)
    - [Requirements](#requirements)
    - [Clone the Repository](#clone-the-repository)
    - [Create the Docker Environment File](#create-the-docker-environment-file)
    - [Build the Containers](#build-the-containers)
    - [Start the Development Server](#start-the-development-server)
  - [Environment Configuration](#environment-configuration)
  - [Email OTP Authentication](#email-otp-authentication)
    - [Request OTP](#request-otp)
    - [Verify OTP](#verify-otp)
  - [Real Email Delivery with Brevo SMTP](#real-email-delivery-with-brevo-smtp)
  - [API Documentation](#api-documentation)
  - [API Modules](#api-modules)
  - [Development Workflow](#development-workflow)
    - [Common Local Workflow](#common-local-workflow)
  - [Testing](#testing)
  - [Celery and Background Jobs](#celery-and-background-jobs)
  - [Local Email Testing](#local-email-testing)
    - [1. Console Email Backend](#1-console-email-backend)
    - [2. Mailpit](#2-mailpit)
    - [3. Brevo SMTP](#3-brevo-smtp)
  - [Database](#database)
  - [Security Notes](#security-notes)
  - [Production Deployment Notes](#production-deployment-notes)
  - [Current Status](#current-status)
  - [License](#license)

---

## Project Overview

MallByte API provides the backend foundation for a marketplace application with multiple operational areas:

- customer authentication and account management
- seller onboarding and seller-specific operations
- product catalog management
- inventory and stock tracking
- carts, orders, payments, shipping, discounts, and returns
- reviews, notifications, and support tickets
- admin-facing content and navigation management
- analytics, scheduled reports, alerts, and observability

The backend is split into separate Django apps to keep business domains isolated and maintainable. This makes the codebase easier to extend, test, and connect to a future frontend.

---

## Project Documentation

A more detailed backend case study is available here:

[Detailed Backend Documentation](https://petite-pheasant-cb4.notion.site/MallByte-Backend-API-Project-Case-Study-3b673a96044080c085e4d3b46b806a9a)

---

## Core Features

### Authentication and Accounts

- Email-based user authentication
- OTP-based login and registration flow
- JWT access and refresh tokens
- Optional phone number as profile/contact information
- Email verification status
- Password reset flow
- Seller application and seller approval flow
- Auth-related rate limiting for OTP, login, and password reset endpoints

### Authorization and Admin Control

- Role-based access control
- Custom roles and permissions
- User-role assignment
- Admin-focused management APIs
- Permission checks for protected resources

### Commerce Modules

- Product catalog
- Product categories, variants, tags, media, and QR codes
- Inventory and stock movement tracking
- Cart and checkout-related flows
- Orders and order items
- Payment module
- Shipping module
- Discounts and promotions
- Returns management

### Customer Experience Modules

- Product reviews
- Review voting
- Notifications and notification preferences
- Support tickets
- Ticket tags, attachments, and audit history

### Platform Operations

- Content and navigation management
- Analytics dashboards
- Time-series and breakdown reports
- Scheduled reports with Celery and django-celery-beat
- Observability and health monitoring
- Request logs, error logs, audit logs, alerts, and Celery task logs

---

## Tech Stack

- Python 3.13
- Django 5.2
- Django REST Framework
- PostgreSQL
- Redis
- Celery
- django-celery-beat
- Simple JWT
- drf-spectacular
- django-filter
- django-cors-headers
- Docker
- Docker Compose
- Makefile-based developer workflow

---

## Architecture

MallByte follows a modular Django architecture. Each major business capability lives in its own Django app under `apps/`.

The backend is organized around clear boundaries:

- `accounts` handles identity, authentication, OTP, users, and seller application logic.
- `rbac` handles roles, permissions, and access control.
- `products` handles product catalog data.
- `inventory` handles stock-related operations.
- `orders`, `payments`, `shipping`, `discounts`, and `returns` handle commerce workflows.
- `reviews`, `notifications`, and `support` handle customer-facing engagement features.
- `content` handles CMS-like platform content.
- `analytics` handles reporting and scheduled analytics output.
- `observability` handles request logs, error logs, audits, health checks, alerts, and background task visibility.

The project uses PostgreSQL for persistent data, Redis for cache/broker-related infrastructure, Celery for background work, and JWT for API authentication.

---

## Project Structure

```text
mallbyte-api/
├── apps/
│   ├── accounts/
│   ├── analytics/
│   ├── content/
│   ├── discounts/
│   ├── inventory/
│   ├── notifications/
│   ├── observability/
│   ├── orders/
│   ├── payments/
│   ├── products/
│   ├── rbac/
│   ├── returns/
│   ├── reviews/
│   ├── shipping/
│   └── support/
├── config/
│   ├── settings/
│   ├── celery.py
│   ├── urls.py
│   └── views.py
├── docker/
│   └── entrypoint.sh
├── requirements/
│   ├── base.txt
│   └── development.txt
├── compose.yaml
├── compose.dev.yaml
├── Dockerfile
├── Makefile
├── manage.py
└── README.md
```

---

## Getting Started with Docker

The recommended local development setup uses Docker Compose.

The local stack includes:

- Django web container
- PostgreSQL database
- Redis
- optional Celery worker
- optional Celery beat
- optional Mailpit email testing UI

PostgreSQL is kept inside the Docker network and is not published directly to the host machine.

### Requirements

Install the following tools before running the project:

- Docker
- Docker Compose
- Make

Check the installed versions:

```bash
docker --version
docker compose version
make --version
```

### Clone the Repository

```bash
git clone https://github.com/sinamoghtaderfar/mallbyte-api.git
cd mallbyte-api
```

### Create the Docker Environment File

```bash
cp .env.docker.example .env.docker
```

Update `.env.docker` if needed. Do not commit this file.

### Build the Containers

```bash
make build
```

### Start the Development Server

```bash
make up
```

Or run it in the background:

```bash
make up-detach
```

The backend will be available at:

```text
http://localhost:8000/
```

---

## Environment Configuration

The project uses environment variables for Django, PostgreSQL, Redis, Celery, CORS, and email settings.

For Docker development, start from:

```bash
cp .env.docker.example .env.docker
```

Example Docker development configuration:

```env
DJANGO_SETTINGS_MODULE=config.settings.base
DEBUG=True
SECRET_KEY=django-insecure-local-docker-only

ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,web
CORS_ALLOW_ALL_ORIGINS=True

DB_NAME=mallbyte_db
DB_USER=mallbyte_user
DB_PASSWORD=mallbyte_password
DB_HOST=db
DB_PORT=5432

REDIS_URL=redis://redis:6379/0
CACHE_REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DEFAULT_FROM_EMAIL=noreply@mallbyte.local
OTP_EMAIL_SUBJECT=Your MallByte verification code
OTP_CODE_EXPIRY_SECONDS=300
```

Never commit real values for:

- `SECRET_KEY`
- database passwords
- SMTP usernames or passwords
- API keys
- JWT-related secrets
- production environment files

---

## Email OTP Authentication

MallByte supports email-based OTP authentication.

The authentication flow is:

1. The client sends an email address to the OTP request endpoint.
2. The backend generates a short OTP code.
3. The backend stores the OTP metadata.
4. The backend sends the OTP code by email.
5. The user enters the OTP code in the frontend.
6. The frontend sends the code to the verification endpoint.
7. The backend verifies the code and returns JWT tokens.

### Request OTP

```bash
curl -X POST http://localhost:8000/api/auth/otp/request/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com"}'
```

Example response:

```json
{
  "message": "OTP sent successfully",
  "delivery_channel": "email",
  "email": "us***@example.com",
  "expires_in": 300
}
```

### Verify OTP

```bash
curl -X POST http://localhost:8000/api/auth/otp/verify/ \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","code":"123456"}'
```

Example response:

```json
{
  "user": {
    "id": 1,
    "email": "user@example.com",
    "phone": null,
    "full_name": "User user",
    "is_seller": false,
    "email_verified": true
  },
  "refresh": "refresh-token",
  "access": "access-token",
  "is_new": true
}
```

Use the access token for authenticated API calls:

```bash
curl http://localhost:8000/api/products/ \
  -H "Authorization: Bearer your-access-token"
```

---

## Real Email Delivery with Brevo SMTP

For local testing, the console email backend is enough. For real email delivery, configure SMTP in `.env.docker`.

Example Brevo SMTP configuration:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp-relay.brevo.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_USE_SSL=False

EMAIL_HOST_USER=your-brevo-smtp-login
EMAIL_HOST_PASSWORD=your-brevo-smtp-key

DEFAULT_FROM_EMAIL="MallByte <your-verified-sender@example.com>"
OTP_EMAIL_SUBJECT=Your MallByte verification code
OTP_CODE_EXPIRY_SECONDS=300
```

Important notes:

- The sender email must be verified in Brevo.
- Use a Brevo SMTP key as the SMTP password.
- Do not commit real SMTP credentials.
- For production, use a proper domain-based sender such as `noreply@yourdomain.com`.

After changing `.env.docker`, restart the containers:

```bash
make down
make up-detach
```

---

## API Documentation

Useful local URLs:

```text
Backend landing page:  http://localhost:8000/
Django admin:          http://localhost:8000/admin/
OpenAPI schema:        http://localhost:8000/api/schema/
Swagger UI:            http://localhost:8000/swagger/
Health endpoint:       http://localhost:8000/api/observability/health/
```

The root endpoint returns service metadata and useful API links.

---

## API Modules

The backend exposes the following top-level API groups:

| Module         | Base Path             | Purpose                                                          |
| -------------- | --------------------- | ---------------------------------------------------------------- |
| Authentication | `/api/auth/`          | OTP, account, login, profile, password reset, seller application |
| RBAC           | `/api/rbac/`          | roles, permissions, and user role assignments                    |
| Products       | `/api/products/`      | product catalog and product-related operations                   |
| Inventory      | `/api/inventory/`     | stock and inventory management                                   |
| Orders         | `/api/orders/`        | carts, checkout, and orders                                      |
| Payments       | `/api/payments/`      | payment-related APIs                                             |
| Shipping       | `/api/shipping/`      | shipping addresses and shipping operations                       |
| Discounts      | `/api/discounts/`     | discounts and promotional rules                                  |
| Returns        | `/api/returns/`       | return management                                                |
| Notifications  | `/api/notifications/` | user notifications and preferences                               |
| Reviews        | `/api/reviews/`       | product reviews and review votes                                 |
| Support        | `/api/support/`       | support tickets, tags, attachments, and audit history            |
| Content        | `/api/content/`       | platform content and navigation                                  |
| Analytics      | `/api/analytics/`     | dashboards, reports, alerts, and scheduled reports               |
| Observability  | `/api/observability/` | health checks, logs, audit records, alerts, and task logs        |

---

## Development Workflow

The project includes a Makefile for common development commands.

```bash
make build              # Build Docker images
make up                 # Start the local development stack
make up-detach          # Start the stack in the background
make up-build           # Start the stack and rebuild images
make down               # Stop containers
make down-volumes       # Stop containers and remove Docker volumes
make logs               # Follow Django logs
make bash               # Open a shell inside the web container
make shell              # Open Django shell
make migrate            # Run database migrations
make makemigrations     # Create new migrations
make createsuperuser    # Create Django superuser
make check              # Run Django system checks
make test               # Run the test suite
make psql               # Open PostgreSQL shell
make celery             # Start Celery worker and Celery beat
make tools              # Start optional development tools
```

### Common Local Workflow

```bash
make up-detach
make logs
make check
make test
```

When dependencies change:

```bash
make build
make up-detach
```

When models change:

```bash
make makemigrations
make migrate
```

---

## Testing

Run Django system checks:

```bash
make check
```

Run the full test suite:

```bash
make test
```

The test command uses `--noinput`, so Django can recreate an old test database automatically when needed.

For app-specific tests, open a shell inside the web container:

```bash
make bash
```

Then run a specific test module, for example:

```bash
python manage.py test apps.accounts --failfast -v 2
```

---

## Celery and Background Jobs

Celery is available through a Docker Compose profile.

Start Celery worker and Celery beat:

```bash
make celery
```

The project uses:

- Redis as Celery broker
- Redis as result backend
- django-celery-beat for database-backed schedules

This is used for background jobs such as scheduled reporting and operational tasks.

---

## Local Email Testing

There are three practical ways to test email flows locally.

### 1. Console Email Backend

This is the safest default for local development. Emails are printed in the Django logs instead of being sent.

```env
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

### 2. Mailpit

Start local tools:

```bash
make tools
```

Mailpit UI:

```text
http://localhost:8025/
```

To route emails to Mailpit, configure `.env.docker` like this:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=mailpit
EMAIL_PORT=1025
EMAIL_USE_TLS=False
EMAIL_USE_SSL=False
DEFAULT_FROM_EMAIL="MallByte <noreply@mallbyte.local>"
```

### 3. Brevo SMTP

Use Brevo SMTP when you want to test real email delivery.

Keep SMTP credentials only in `.env.docker` or another ignored environment file.

---

## Database

The Docker setup uses PostgreSQL 16.

The database service is available only inside the Docker network. It is not exposed as a public host port in the base Compose configuration.

Open PostgreSQL shell:

```bash
make psql
```

Reset the Docker database:

```bash
make down-volumes
make up
```

This removes Docker volumes and recreates the local Docker database. It does not affect a PostgreSQL installation running directly on your machine.

---

## Security Notes

The project includes several security-focused practices for development and future deployment:

- Environment-based configuration
- JWT authentication
- OTP-based email verification
- Rate limits for sensitive auth endpoints
- PostgreSQL kept inside the Docker network for local Docker development
- Separate production settings module
- No real credentials in example environment files

Development reminders:

- Do not commit `.env` or `.env.docker`.
- Do not commit SMTP credentials.
- Do not commit real database passwords.
- Do not commit access or refresh tokens.
- Use `DEBUG=False` in production.
- Use a strong production `SECRET_KEY`.
- Restrict `ALLOWED_HOSTS` and CORS in production.
- Use HTTPS and secure cookie settings in production.
- Use a restricted production database user.
- Use a verified email sender or authenticated domain for production email.

---

## Production Deployment Notes

The current Docker setup is intended for local development.

A production deployment should be handled separately and should include:

- production Django settings
- `DEBUG=False`
- strong secret management
- Gunicorn or another production WSGI/ASGI server
- Nginx, Traefik, or another reverse proxy
- HTTPS certificates
- secure CORS and CSRF configuration
- static file collection and serving strategy
- production PostgreSQL credentials
- database backups
- log retention
- monitoring and alerting
- proper email sender domain authentication
- CI/CD pipeline

---

## Current Status

The backend currently supports:

- Docker-based local development
- PostgreSQL and Redis services
- email OTP authentication
- JWT token authentication
- modular API structure
- Swagger/OpenAPI schema generation
- observability and health endpoints
- optional Celery worker and beat services
- Makefile-based local workflow
- automated test execution through Django test runner

The frontend is not included in this repository. It should be developed as a separate client application that communicates with the backend API.

---

## License

This project is licensed under the [MIT License](LICENSE).
