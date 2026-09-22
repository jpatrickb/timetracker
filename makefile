init-db:
	rm -f dev/dev.db
	sqlite3 dev/dev.db < src/timetracker/migrations/001_initial.sql
