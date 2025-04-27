# Use an official Python runtime as a parent image
FROM python:3.12-slim

LABEL authors="jcoller"
LABEL name="inventory"

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app/

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port that the app will run on
EXPOSE 8000

# Set environment variable to avoid Python buffering
ENV PYTHONUNBUFFERED=1

# Run Django migrations when the container starts
CMD ["python manage.py migrate && gunicorn inventory_management_site.wsgi:application --bind 127.0.0.1:8000"]