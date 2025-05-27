FROM python:3.9

# Install required system packages, including network tools and font packages
RUN apt-get update && apt-get install -y \
    net-tools \
    iproute2 \
    iputils-ping \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# ... rest of your Dockerfile content ...
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

# Make sure the entrypoint.sh file is executable
RUN chmod +x entrypoint.sh

COPY entrypoint.sh /app/entrypoint.sh


# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]
