#!/usr/bin/env sh
env/bin/celery -A solotodo_core multi start general reports storescraper -Q:general general -c:general 20 -Q:reports reports -c:reports 5 -Q:storescraper storescraper -c:storescraper 20 --logfile=solotodo_core/logs/celery/%n.log --pidfile=solotodo_core/pids/celery/%n.pid -l info
