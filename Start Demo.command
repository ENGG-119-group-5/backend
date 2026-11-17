#!/bin/bash
# Double-click this file (macOS) to start the VC Due Diligence Tool demo.
# It opens in your browser at http://localhost:3000. Close this window (or press Ctrl+C) to stop.
#
# Needs: Docker Desktop, Python 3.10+, Node.js 20+, git.
# The web app must sit next to this repo, in a folder named "web-app" or "webapp".
# If it is missing, this script clones it there. The first run also installs
# the Python and Node packages, which takes a few minutes.

# Web app branch used when cloning.
WEBAPP_BRANCH="main"
WEBAPP_REPO="https://github.com/ENGG-119-group-5/webapp.git"

cd "$(dirname "$0")"
BACKEND="$(pwd)"
PARENT="$(dirname "$BACKEND")"
export PATH="$PATH:/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:/opt/homebrew/bin"

step() { printf "\n\033[1;32m==> %s\033[0m\n" "$1"; }
fail() { printf "\n\033[1;31mProblem: %s\033[0m\n" "$1"; read -r -p "Press Enter to close."; exit 1; }

command -v git >/dev/null || fail "git is not installed. Install it with: xcode-select --install"
command -v python3 >/dev/null || fail "Python 3 is not installed. Get it from https://www.python.org/downloads/"
command -v npm >/dev/null || fail "Node.js is not installed. Get it from https://nodejs.org/"

for port in 3000 8000; do
  if lsof -nP -iTCP:$port -sTCP:LISTEN >/dev/null 2>&1; then
    fail "Port $port is already in use. Close the other terminal window running the app (or restart your Mac), then try again."
  fi
done

# Find the web app next to this repo, or clone it.
WEB=""
for name in web-app webapp; do
  [ -f "$PARENT/$name/package.json" ] && WEB="$PARENT/$name" && break
done
if [ -z "$WEB" ]; then
  step "Downloading the web app into $PARENT/webapp"
  git clone --branch "$WEBAPP_BRANCH" "$WEBAPP_REPO" "$PARENT/webapp" \
    || fail "Could not clone $WEBAPP_REPO. Check that you have access to the ENGG-119-group-5 GitHub organization."
  WEB="$PARENT/webapp"
fi
echo "Web app: $WEB (branch: $(git -C "$WEB" branch --show-current))"

step "Starting Docker (this can take a minute the first time)"
open -a Docker || fail "Docker Desktop is not installed. Get it from https://www.docker.com/products/docker-desktop/"
until docker info >/dev/null 2>&1; do sleep 2; done

step "Starting the database"
docker compose up -d >/dev/null 2>&1 || fail "Could not start the database (docker compose up)."
until docker compose ps --format '{{.Status}}' | grep -q healthy; do sleep 2; done

if [ ! -x .venv/bin/uvicorn ]; then
  step "Installing the Python packages (first run only)"
  python3 -m venv .venv || fail "Could not create the Python environment."
  .venv/bin/pip install -q -e '.[dev]' || fail "Could not install the Python packages."
fi
source .venv/bin/activate

step "Loading the demo data"
mkdir -p data/processed
scripts/load_demo.sh >/dev/null 2>&1 || fail "Could not load the demo data."

step "Starting the backend"
uvicorn api.main:app --app-dir src --port 8000 --log-level warning &
API_PID=$!

cd "$WEB" || fail "Web app folder not found."
if [ ! -d node_modules ]; then
  step "Installing the web app packages (first run only)"
  npm ci --silent || fail "Could not install the web app packages (npm ci)."
fi

step "Starting the website"
echo "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" > .env.local
npx next dev -p 3000 >/tmp/vc-demo-web.log 2>&1 &
WEB_PID=$!

cleanup() {
  printf "\nStopping the demo...\n"
  kill $API_PID $WEB_PID 2>/dev/null
  cd "$BACKEND" && docker compose stop >/dev/null 2>&1
}
trap cleanup EXIT INT TERM

until curl -s -o /dev/null http://localhost:3000/ && curl -s -o /dev/null http://localhost:8000/samples; do sleep 1; done
# Load each page once so the audience never waits for the first compile.
curl -s -o /dev/null http://localhost:3000/ ; curl -s -o /dev/null http://localhost:3000/technology/2021-023 ; curl -s -o /dev/null http://localhost:3000/search

open http://localhost:3000
step "Ready! The app is open at http://localhost:3000"
echo "Keep this window open during the demo. Close it (or press Ctrl+C) to stop everything."
wait
