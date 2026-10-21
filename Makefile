VPS ?= root@191.252.101.59
REMOTE_DIR ?= /opt/myfinance
IMAGE ?= myfinance:latest
SERVICE ?= bot

.DEFAULT_GOAL := help

.PHONY: help install run api test build up down restart logs logs-bot logs-api ps pull deploy

help:
	@echo "install  - uv sync"
	@echo "run      - run the Telegram bot locally"
	@echo "api      - run FastAPI locally with reload"
	@echo "test     - run the test suite"
	@echo "build    - build the Docker image"
	@echo "up       - start api+bot with Docker Compose"
	@echo "down     - stop the containers"
	@echo "restart  - restart the containers"
	@echo "logs     - follow VPS logs (SERVICE=bot|api)"
	@echo "logs-bot - follow the VPS bot logs"
	@echo "logs-api - follow the VPS API logs"
	@echo "ps       - container status"
	@echo "pull     - git pull --ff-only"
	@echo "deploy   - push, pull on VPS, rebuild and restart"

install:
	uv sync

run:
	uv run python bot.py

api:
	uv run uvicorn main:app --reload

test:
	uv run pytest -q

build:
	docker build -t $(IMAGE) .

up:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart

logs:
	ssh $(VPS) 'cd $(REMOTE_DIR) && docker compose logs -f --tail=100 $(SERVICE)'

logs-bot:
	ssh $(VPS) 'cd $(REMOTE_DIR) && docker compose logs -f --tail=100 bot'

logs-api:
	ssh $(VPS) 'cd $(REMOTE_DIR) && docker compose logs -f --tail=100 api'

ps:
	docker compose ps

pull:
	git pull --ff-only

deploy:
	git push origin main
	ssh $(VPS) 'cd $(REMOTE_DIR) && git pull --ff-only && docker compose up -d --build'
