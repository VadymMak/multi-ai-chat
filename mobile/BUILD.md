# Mamalog Mobile — Build Guide

## Prerequisites

- Node.js 18+
- pnpm 9+
- EAS CLI: `npm install -g eas-cli`
- Expo account: `eas login`

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `EXPO_PUBLIC_API_URL` | Backend API base URL | `https://mamalog.vercel.app` |

For local development, create `apps/mobile/.env`:
```
EXPO_PUBLIC_API_URL=http://localhost:3000
```

## Build Profiles

### Development (with dev client)
```bash
cd apps/mobile
eas build --profile development --platform android
```

### Preview APK (internal testing)
```bash
cd apps/mobile
eas build --profile preview --platform android
```
Produces a `.apk` file — directly installable on Android devices.

### Production (Google Play)
```bash
cd apps/mobile
eas build --profile production --platform android
```
Produces an `.aab` bundle for Google Play submission.

## Local Development

```bash
# Start Metro bundler
cd apps/mobile
npx expo start

# Scan QR with Expo Go app (development only)
```

## First-time EAS Setup

```bash
# Login to Expo
eas login

# Link project (creates projectId in app.json)
eas init

# Build preview APK
eas build --profile preview --platform android --local
```

## Project IDs

- Android package: `com.mamalog.app`
- iOS bundle: `com.mamalog.app`
