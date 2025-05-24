#!/usr/bin/env zsh
source ~/.zshrc

cd "${0%/*}"
source env/bin/activate
celery multi stopwait -A solotodo_core storescraper --logfile=solotodo_core/logs/celery/%n.log --pidfile=solotodo_core/pids/celery/%n.pid -E -l info