#!/bin/sh

# Exit on error
set -e

# Run database migrations
echo "Running migrations..."
python manage.py migrate

# Collect static files (optional)
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Start Gunicorn
echo "Starting Gunicorn..."
exec gunicorn inventory_management_site.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --threads 4 \
    --worker-class gthread
