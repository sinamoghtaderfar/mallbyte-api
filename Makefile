.RECIPEPREFIX := >
COMPOSE=docker compose -f compose.yaml -f compose.dev.yaml

.PHONY: build up up-build up-detach down down-volumes logs bash shell migrate makemigrations createsuperuser check test celery tools psql

build:
>$(COMPOSE) build

up:
>$(COMPOSE) up

up-build:
>$(COMPOSE) up --build

up-detach:
>$(COMPOSE) up -d

down:
>$(COMPOSE) down

down-volumes:
>$(COMPOSE) down -v

logs:
>$(COMPOSE) logs -f web

bash:
>$(COMPOSE) exec web sh

shell:
>$(COMPOSE) exec web python manage.py shell

migrate:
>$(COMPOSE) exec web python manage.py migrate

makemigrations:
>$(COMPOSE) exec web python manage.py makemigrations

createsuperuser:
>$(COMPOSE) exec web python manage.py createsuperuser

check:
>$(COMPOSE) exec web python manage.py check

test:
>$(COMPOSE) exec web python manage.py test --failfast --noinput -v 2

celery:
>$(COMPOSE) --profile celery up

tools:
>$(COMPOSE) --profile tools up

psql:
>$(COMPOSE) exec db psql -U mallbyte_user -d mallbyte_db
