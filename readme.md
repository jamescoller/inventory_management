[![Deploy to Synology NAS](https://github.com/jamescoller/inventory_management/actions/workflows/deploy.yml/badge.svg)](https://github.com/jamescoller/inventory_management/actions/workflows/deploy.yml)

## 1. Clone and Build
```bash
git clone https://github.com/jamescoller/inventory_management
cd inventory_management
docker-compose build
```

## 2. Run the App
```bash
docker-compose up -d
```
or, to rebuild it first [same as below]
```bash
docker-compose up --build --remove-orphans
```

### Alternative: Deploy via PyCharm

You can deploy directly from PyCharm, at which case, the port will be 8000.

## 3. Access it
- Open your browser at: `http://localhost:8080`

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
