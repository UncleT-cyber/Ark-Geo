# ArkGeo — Repository Knowledge Base

## Project Overview
ArkGeo is a modular AI geolocation and personal safety ecosystem with three applications:
- **arkgeo-backend** — FastAPI modular "Brain" AI engine (4-tier pipeline)
- **arkgeo-mobile** — React Native / Expo tactical safety HUD
- **arkgeo-investigator-web** — React / Vite forensic OSINT dashboard

## Repository
- GitHub: https://github.com/UncleT-cyber/Ark-Geo.git
- Working directly on `main` branch (no feature branches / PRs)

## Architecture: The Brain (4-Tier Pipeline)
1. **Tier 1 — EXIF Metadata**: deterministic GPS extraction (piexif + Pillow)
2. **Tier 2 — Vision Ensemble**: multi-API Vision aggregator (GeoSpy/GeoInfer)
3. **Tier 3 — Clue Extractors**: architectural, botanical, OCR, infrastructure, indoor
4. **Tier 4 — Consensus Engine**: Bayesian confidence scorer + pin aggregator

## Key Commands

### Backend
```bash
cd arkgeo-backend
python -m pytest tests/ -q              # run tests (19 passing)
python -m uvicorn main:app --reload     # start dev server (port 8000)
```

### Web Portal
```bash
cd arkgeo-investigator-web
npm install
npx tsc --noEmit                        # type-check (clean)
npx vite build                          # production build
npm run dev                             # dev server (port 5173, proxies /api → :8000)
```

### Mobile
```bash
cd arkgeo-mobile
npm install
npx expo start                          # Expo dev server
```

## Tech Stack
- Backend: Python 3.13, FastAPI, Pillow, piexif, pydantic, python-jose, bcrypt, boto3, httpx
- Mobile: React Native 0.74, Expo 51, expo-camera/location/av/sqlite/secure-store, react-native-maps
- Web: React 18, Vite 5, Leaflet, axios, TypeScript 5

## Security
- AES-256-GCM encryption (app/core/security.py)
- JWT auth + bcrypt password hashing (no passlib — uses bcrypt directly)
- SHA-256 chain-of-custody hashing
- Zero-retention mode for forensic uploads
- Encrypted SQLite offline queue (mobile)

## Design Language
- OLED Dark Slate (#0B0F17), Electric Cyan (#38BDF8), Emergency Red (#EF4444)
- Tactical HUD aesthetic, mono fonts for telemetry data

## Testing
- pytest-asyncio mode=STRICT
- 19 tests across metadata extraction, consensus engine, and pipeline integration
- Known non-blocking warning: httpx/TestClient deprecation in Starlette

## Conventions
- Git: user.name=openhands, user.email=openhands@all-hands.dev
- Commits include `Co-authored-by: openhands <openhands@all-hands.dev>`
- No node_modules, .env, __pycache__, dist/ in version control
