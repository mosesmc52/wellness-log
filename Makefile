.PHONY: build up upd down restart logs ps test test-email weekly monthly db-download db-upload clean

build:
	docker compose build

up:
	docker compose up

upd:
	docker compose up -d

down:
	docker compose down --remove-orphans

restart:
	docker compose restart

logs:
	docker compose logs -f

ps:
	docker compose ps

test:
	docker compose build web
	docker compose run --rm -e SKIP_DB_BOOTSTRAP=1 web pytest

test-email:
	docker compose run --rm web poetry run python -c "import html, os; from wellness_log.email_service import send_report; url = os.getenv('APP_URL', 'http://localhost:8000'); safe_url = html.escape(url, quote=True); send_report('Open wellness-log', f'Open your wellness log: {url}', f'<p>Open your <a href=\"{safe_url}\">wellness log page</a>.</p>'); print(f'Email sent successfully with link: {url}')"

weekly:
	docker compose run --rm web poetry run python -m wellness_log.reports weekly

monthly:
	docker compose run --rm web poetry run python -m wellness_log.reports monthly

db-download:
	docker compose run --rm -e SKIP_DB_BOOTSTRAP=1 web poetry run python spaces_sqlite_sync.py download

db-upload:
	docker compose run --rm -e SKIP_DB_BOOTSTRAP=1 web poetry run python spaces_sqlite_sync.py upload

clean:
	docker compose down --remove-orphans --rmi local
