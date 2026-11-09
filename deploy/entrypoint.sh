#!/bin/sh
set -e

exec supervisord -n -c /app/deploy/supervisord.conf
