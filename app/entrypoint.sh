#!/bin/bash
# Start cron
service cron start

# Forward cron logs to docker logs
touch /var/log/cron.log
tail -f /var/log/cron.log &

# Run main app
exec "$@"
