# 🐳 GitHub Actions Self-Hosted Runner (Dockerized)

This folder contains a Dockerized GitHub Actions runner for the `inventory_management` repository. It registers itself
dynamically with GitHub on startup using a GitHub Personal Access Token (PAT), and automatically reconnects on restart.

---

## 📦 Contents

- `Dockerfile` – Builds a runner with all dependencies.
- `entrypoint.sh` – Dynamically registers the runner with GitHub using a PAT.
- `docker-compose.yml` – For quick local deployment.
- `.env` – (not included) You supply this with your GitHub PAT.

---

## 🚀 Quick Start

### 1. 🔑 Create a GitHub PAT (Personal Access Token)

Go to [https://github.com/settings/tokens](https://github.com/settings/tokens) and create a **fine-scoped PAT** with:

- `repo`
- `admin:repo_hook`

This is used only for requesting a **temporary runner registration token**.

---

### 2. 🛠️ Create a `.env` File

```env
# .env
GITHUB_PAT=ghp_yourGeneratedToken
