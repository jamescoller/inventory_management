# 🚀 Django + Docker + Gunicorn + Nginx Cheat Sheet

---

## 1. Dockerize Django App

- Create a `Dockerfile`:

  ```Dockerfile
  FROM python:3.11
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install -r requirements.txt
  COPY . .
  ```

- Create an `entrypoint.sh`:

  ```bash
  #!/bin/sh
  set -e
  python manage.py migrate
  python manage.py collectstatic --noinput
  exec gunicorn inventory_management_site.wsgi:application --bind 0.0.0.0:8000 --workers 3
  ```

---

## 2. Docker Compose Setup

- Basic `docker-compose.yml`:
  ```yaml
  version: '3'
  services:
    web:
      build: .
      volumes:
        - .:/app
        - static_volume:/static/
      expose:
        - "8000"
      command: ["/entrypoint.sh"]

    nginx:
      image: nginx:latest
      ports:
        - "80:80"
      volumes:
        - static_volume:/static/
        - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf
      depends_on:
        - web

  volumes:
    static_volume:
  ```

---

## 3. Nginx Config

- `nginx/nginx.conf`:
  ```nginx
  server {
      listen 80;

      location /static/ {
          alias /static/;
      }

      location / {
          proxy_pass http://web:8000;
          proxy_set_header Host $host;
          proxy_set_header X-Real-IP $remote_addr;
          proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header X-Forwarded-Proto $scheme;
      }
  }
  ```

---

## 4. Important Django Settings

- In `settings.py`:
  ```python
  DEBUG = False
  ALLOWED_HOSTS = ['yourdomain.com', 'www.yourdomain.com', 'localhost']
  STATIC_URL = '/static/'
  STATIC_ROOT = '/static/'
  ```

---

## 5. Commands to Deploy

```bash
chmod +x entrypoint.sh
docker-compose down
docker-compose up --build
```

---

# 🛡️ Upgrade Path (Later):

- Add Let's Encrypt SSL (automatic HTTPS)
- Switch from SQLite ➔ PostgreSQL for production
- Add `restart: always` to services
- Health checks, monitoring, scaling

---

# 🧐 Pro Tip:

**Never run Django's ****\`\`**** in production!**\
Always use **Gunicorn** + **Nginx** combo. ✅

---

# 🎯 TL;DR:

You now have a **professional deployment base** — easy to maintain, scalable when you're ready, and cleanly separated.