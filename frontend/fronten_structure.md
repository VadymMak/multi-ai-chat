# Frontend Project Structure (React + TypeScript)

_A snapshot of the current directory layout before frontend refactoring_

### Previous

📁 frontend  
├── 📁 build  
├── 📁 node_modules  
├── 📁 public  
│ ├── favicon.ico  
│ ├── index.html  
│ ├── logo192.png  
│ ├── logo512.png  
│ └── manifest.json  
├── 📁 src  
│ ├── 📁 api  
│ ├── 📁 components  
│ ├── 📁 hooks  
│ ├── api.ts  
│ ├── App.module.css  
│ ├── App.test.tsx  
│ ├── App.tsx  
│ ├── index.tsx  
│ ├── logo.svg  
│ ├── react-app-env.d.ts  
│ ├── reportWebVitals.ts  
│ ├── service-worker.ts  
│ ├── serviceWorkerRegistration.ts  
│ ├── setupTests.ts  
│ └── types.ts  
├── .env  
├── .gitignore  
├── Dockerfile  
├── mintty.2025-07-13_10-17-04.png  
├── package-lock.json  
├── package.json  
├── README.md  
├── tsconfig.json

### Proposed

# 📁 Frontend Project Structure (as of July 2025)

This document captures the current structure of the `frontend/` directory in the multi-AI assistant project.

## 📦 Project Layout

# 📁 Proposed Frontend Structure After Refactoring

```plaintext
frontend/
├── public/
│   ├── favicon.ico
│   ├── index.html
│   ├── logo192.png
│   ├── logo512.png
│   └── manifest.json
├── src/
│   ├── assets/                      # Static images, icons, fonts
│   ├── components/                 # Reusable UI components
│   │   ├── Chat/
│   │   │   ├── ChatArea.tsx
│   │   │   ├── ChatMessage.tsx
│   │   │   └── TypingIndicator.tsx
│   │   ├── Layout/
│   │   │   ├── Header.tsx
│   │   │   └── Footer.tsx
│   │   └── common/                 # Buttons, modals, etc.
│   ├── features/                   # Feature-specific modules
│   │   └── aiConversation/
│   │       ├── AiChat.tsx
│   │       └── AiSelector.tsx
│   ├── hooks/                      # Custom React hooks
│   │   ├── useAiChat.ts
│   │   └── useTypingEffect.ts
│   ├── services/                   # API logic and interceptors
│   │   ├── apiClient.ts            # axios instance or fetch wrapper
│   │   ├── interceptors.ts
│   │   └── aiApi.ts                # LLM endpoint calls
│   ├── store/                      # Zustand, Redux, or Context
│   │   ├── chatStore.ts
│   │   ├── modelStore.ts
│   │   └── memoryStore.ts
│   ├── types/                      # TypeScript interfaces and types
│   │   ├── ai.ts
│   │   └── chat.ts
│   ├── utils/                      # Utility functions
│   │   ├── formatDate.ts
│   │   └── tokenCounter.ts
│   ├── App.tsx
│   ├── App.module.css
│   ├── index.tsx
│   ├── serviceWorker.ts
│   ├── serviceWorkerRegistration.ts
│   ├── reportWebVitals.ts
│   └── react-app-env.d.ts
├── .env
├── Dockerfile
├── docker-compose.yml
├── package.json
├── README.md
└── tsconfig.json

```

# 🌐 Multi-AI Chat Assistant — Frontend Architecture Decisions

## 🖼️ Styling Strategy

**Framework:** Tailwind CSS  
**Approach:** Mobile-first, utility-first design for full responsiveness across:

- 📱 Mobile
- 💻 Desktop
- 🖥️ Ultra-wide monitors

### ✅ Tailwind Setup Notes

- Use responsive classes: `p-4 md:p-6 lg:p-8`
- Customize `tailwind.config.js` for breakpoints if needed
- Reuse styles via `@apply` in `.module.css` or custom components

### Example:

```tsx
<div className="flex flex-col gap-2 p-4 md:flex-row md:gap-4 lg:p-6">...</div>
```

## ✅ Tailwind CSS Manual Setup Summary (React + TypeScript)

### 🧱 1. Installed dependencies:

```bash
npm install -D tailwindcss postcss autoprefixer
```

---

### 🧩 2. Created config files manually:

**📄 **``

```js
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};
```

**📄 **``

```js
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

---

### 🎨 3. Created Tailwind entry CSS file:

**📄 **``

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

---

### 🧵 4. Imported Tailwind styles in your app:

In `src/index.tsx`:

```ts
import "./styles/tailwind.css";
```

---

### 🧠 Editor Tip (optional but recommended):

To fix `@tailwind` unknown warning in VS Code:

- Install the [Tailwind IntelliSense extension](https://marketplace.visualstudio.com/items?itemName=bradlc.vscode-tailwindcss)

---

This setup is now working and will help you bootstrap Tailwind in future projects without relying on `npx tailwindcss init`.
