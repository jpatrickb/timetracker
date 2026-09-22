init-db:
	rm -f dev/dev.db
	TIMETRACKER_DB=dev/dev.db uv run python -c "from timetracker.db import connect; connect().close()"
