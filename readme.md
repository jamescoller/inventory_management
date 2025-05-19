## 1. Clone and Build
```bash
git clone <your-repo-url>
cd <your-project>
docker-compose build
```

## 2. Run the App
```bash
docker-compose up -d
```

## 3. Access it
- Open your browser at: `http://your-server-ip`

## 4. Migrations and Collectstatic
Handled automatically by `entrypoint.sh` during container startup.

## 5. Stopping the App
```bash
docker-compose down
```

---

> For updates, rebuild with:
> ```bash
> docker-compose up --build -d
> ```