#!/usr/bin/env zsh
source ~/.zshrc

cd "${0%/*}"
source env/bin/activate
celery multi start -A solotodo_core general reports -Q:general general -c:general 20 -Q:reports reports -c:reports 5 --logfile=solotodo_core/logs/celery/%n.log --pidfile=solotodo_core/pids/celery/%n.pid -E -l info
