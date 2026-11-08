# wellness-log

`wellness-log` is a small, single-user habit tracker. It presents one daily Yes/No check-in page, stores answers in SQLite, and sends weekly and monthly summaries through Amazon SES. There are no accounts, analytics, journal text, or external services beyond optional email delivery.

## Quick start

Requirements: Docker with the Compose plugin and GNU Make.

```bash
cp .env.example .env
make build
make up
```

Open <http://localhost:8000>. The port is bound to `127.0.0.1` by default and is not exposed to other hosts.

The `web` and `scheduler` containers use the same image and the same named `wellness_data` volume. Habit data therefore survives container recreation, `make down`, and `make clean`.

## Configuration

Edit `.env` before starting the application:

| Variable | Purpose |
|---|---|
| `APP_TIMEZONE` | Time zone used to determine the current calendar date |
| `TZ` | Container and cron scheduling time zone |
| `APP_URL` | URL included in the test email (`http://localhost:8000` by default) |
| `DATABASE_URL` | SQLite connection URL; the provided value points into the persistent volume |
| `AWS_SES_REGION_NAME` | AWS region containing the SES identity (`us-east-1` by default) |
| `AWS_SES_ACCESS_KEY_ID`, `AWS_SES_SECRET_ACCESS_KEY` | Optional static AWS credentials |
| `AWS_SES_SESSION_TOKEN` | Optional token for temporary static credentials |
| `FROM_ADDRESS` | SES sender address |
| `TO_ADDRESSES` | One or more recipient addresses separated by commas |

Keep `.env` private; it is excluded from Git. The web app works without SES configuration. Sending a report requires `FROM_ADDRESS` and `TO_ADDRESSES`; the sender must be a verified SES identity. While an AWS account is in the SES sandbox, every recipient must also be verified. Multiple recipients use a comma-separated value, for example `TO_ADDRESSES=alice@example.com,bob@example.com`.

For local use, set the `AWS_SES_*` credential variables in `.env`. In an AWS environment, leave them blank and boto3 will use its standard credential chain, including IAM roles and container credentials. The assigned identity needs permission for `ses:SendEmail` in the configured region.

## Operations

```bash
make build       # build the shared image
make up          # start web and scheduler in the background
make down        # stop/remove containers, preserving the data volume
make restart     # restart both services
make logs        # follow logs
make ps          # show service status
make test        # run pytest in a container
make test-email  # send a test email through Amazon SES
make weekly      # send the current Monday-Sunday report
make monthly     # send the previous calendar month's report
make clean       # remove containers and local images, preserving data
```

`make test-email` sends every recipient in `TO_ADDRESSES` a link to `APP_URL`. It sends immediately and does not create a weekly or monthly delivery record. Set `APP_URL` to the externally reachable address if the application is hosted somewhere other than the local machine.

For a preview that never sends email or records a delivery, run:

```bash
docker compose run --rm web poetry run python -m wellness_log.reports weekly --dry-run
docker compose run --rm web poetry run python -m wellness_log.reports monthly --dry-run
```

You can add `--date YYYY-MM-DD` to either report command to make a deterministic historical report. Normal weekly execution is scheduled for Sunday at 9:00 PM; monthly execution is scheduled for 9:00 AM on the first day and covers the previous month. Cron uses the configured `TZ`.

Successful delivery periods are recorded in SQLite, preventing repeat sends. An SES failure removes the pending delivery reservation, so the command can be retried. Scheduler and report outcomes appear in `make logs`.

## Testing locally

The supported test command uses Python 3.12 inside Docker:

```bash
make test
```

If Python 3.12 and Poetry are installed on the host, the equivalent is:

```bash
poetry install
poetry run pytest
```

Tests use temporary SQLite databases and a fake SES client; they never contact AWS.

## Database backup and restore

SQLite runs in WAL mode with a 30-second busy timeout. To take a consistent backup while the app is running, use SQLite's backup command from the web container:

```bash
docker compose exec web python -c "import sqlite3; source=sqlite3.connect('/app/data/wellness.db'); backup=sqlite3.connect('/app/data/wellness-backup.db'); source.backup(backup); backup.close(); source.close()"
docker compose cp web:/app/data/wellness-backup.db ./wellness-backup.db
```

To restore, stop the services, copy the backup into a temporary container attached to the volume, then start services again. Keep the original backup until the restored app has been checked. `make down` and `make clean` deliberately do not pass `--volumes`; avoid `docker compose down --volumes` unless you intend to delete all data.

## Adding a habit

Add one `Habit` entry to `wellness_log/habits.py`, choosing a stable unique key and one of the existing groups. The form and both report formats read that central catalogue automatically. Existing dates will count the new habit as unanswered, which is intentional because report denominators represent all scheduled habit-days. Add or update a catalogue assertion in `tests/test_habits.py`, then run `make test`.

## Data model

Each `(date, habit_key)` pair is unique. `completed = true` means Yes, `false` means No, and SQL `NULL` means Unanswered. Timestamps are stored as UTC values. The interface displays and updates only the current date in `APP_TIMEZONE`.
