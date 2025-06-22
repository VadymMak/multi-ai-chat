Multi-AI Chat

Multi-AI Chat is a Progressive Web App (PWA) built with React and TypeScript, featuring a sleek, dark-themed chat interface inspired by xAI's Grok. The application allows users to interact with multiple AI models (Grok from xAI, OpenAI, Anthropic, or all in an AI-to-AI dialog) through a single interface. It supports responsive design, offline capabilities via a service worker, and is ready for deployment to platforms like Netlify.
Features

Grok-Inspired UI: A modern, dark-themed interface with a clean layout, featuring a header with model selection, a scrollable chat area, and an input section.
Model Selection: Choose between Grok (xAI), OpenAI, Anthropic, or "All" for AI-to-AI dialog via a dropdown menu.
Responsive Design: Built with Tailwind CSS, ensuring compatibility across desktop and mobile devices.
PWA Support: Offline functionality and "Add to Home Screen" support via a service worker and manifest.
TypeScript: Type-safe code for robust development.
GitHub Integration: Version control with Git, hosted at https://github.com/VadymMak/multi_ai_chat.

Tech Stack

Frontend: React, TypeScript, Tailwind CSS
PWA: Workbox for service worker, manifest.json for app metadata
Build Tool: Create React App (CRA)
Testing: @testing-library/react, @testing-library/jest-dom, @testing-library/user-event
Version Control: Git, GitHub
Deployment: Configured for Netlify (optional)

Project Structure
multi-ai-chat/
├── public/
│ ├── index.html # HTML entry point
│ ├── manifest.json # PWA manifest
│ └── icons/ # PWA icons (192x192, 512x512)
├── src/
│ ├── App.tsx # Main chat interface component
│ ├── index.tsx # React entry point
│ ├── index.css # Tailwind CSS styles
│ ├── service-worker.ts # Service worker for PWA
│ ├── serviceWorkerRegistration.ts # Service worker registration
│ └── reportWebVitals.ts # Performance monitoring
├── netlify.toml # Netlify deployment configuration
├── package.json # Dependencies and scripts
├── tsconfig.json # TypeScript configuration
└── README.md # This file

Setup Instructions
Prerequisites

Node.js: Version 16 or higher
npm: Version 8 or higher
Git: For version control
VS Code (recommended): With extensions like ESLint and Prettier
Google Chrome: For testing PWA features

Installation

Clone the Repository:
git clone https://github.com/VadymMak/multi_ai_chat.git
cd multi-ai-chat

Install Dependencies:
npm install

Run Locally:
npm start

Opens http://localhost:3000 in your browser.
Test the chat interface by selecting a model (Grok, OpenAI, Anthropic, All), typing messages, and pressing "Send" or Enter.

Build for Production:
npm run build

Creates a production-ready build in the build/ folder.

Test PWA Locally:
npm install -g serve
serve -s build

Opens http://localhost:5000.
Check Chrome DevTools → Application → Service Workers and Manifest for PWA functionality.

Configuration Details
PWA Configuration

Manifest (public/manifest.json):
{
"name": "Multi-AI Chat",
"short_name": "AIChat",
"start_url": "/",
"display": "standalone",
"background_color": "#1a1a1a",
"theme_color": "#007bff",
"icons": [
{
"src": "/icons/icon-192x192.png",
"sizes": "192x192",
"type": "image/png"
},
{
"src": "/icons/icon-512x512.png",
"sizes": "512x512",
"type": "image/png"
}
]
}

Defines app metadata and icons for "Add to Home Screen."

Service Worker (src/service-worker.ts):

Uses Workbox to cache static assets (styles, scripts, images).
Registered in src/serviceWorkerRegistration.ts.

Tailwind CSS

Configured in tailwind.config.js and src/index.css.
Provides responsive, dark-themed styling inspired by Grok’s UI.

Dependencies

Key dependencies in package.json:"dependencies": {
"react": "^19.1.0",
"react-dom": "^19.1.0",
"@testing-library/react": "^16.0.0",
"@testing-library/jest-dom": "^6.4.2",
"@testing-library/user-event": "^14.5.2",
"typescript": "^4.4.2",
"workbox-core": "^6.4.2",
"workbox-precaching": "^6.4.2",
"workbox-routing": "^6.4.2",
"workbox-strategies": "^6.4.2",
"workbox-cacheable-response": "^6.4.2",
"workbox-expiration": "^6.4.2"
}

Git Configuration

Repository: https://github.com/VadymMak/multi_ai_chat
Use HTTPS or SSH for pushes:git remote set-url origin git@github.com:VadymMak/multi_ai_chat.git # SSH

For HTTPS, use a Personal Access Token (PAT) for authentication.

Troubleshooting

DNS Issues:

If git push fails with Could not resolve host: github.com, ensure DNS settings:ipconfig /flushdns
nslookup github.com

Use Google’s DNS (8.8.8.8, 1.1.1.1) in Network Settings.

Test connectivity:curl https://github.com

Service Worker Errors:

If ESLint flags self, ensure src/service-worker.ts has:/_ eslint-disable no-restricted-globals _/
declare const self: ServiceWorkerGlobalScope;

PWA Not Installing:

Verify public/manifest.json and icons exist.
Check Chrome DevTools → Application → Manifest.

Next Steps

Deployment: Deploy to Netlify:
Push to GitHub.
Connect the repository to Netlify and use netlify.toml for build settings.

Backend Integration: Set up a Python backend (e.g., Flask, FastAPI) on DigitalOcean to handle API calls to Grok, OpenAI, and Anthropic.
Offline Caching: Enhance service-worker.ts to cache chat messages for offline use.
AI-to-AI Dialog: Implement logic in App.tsx for multi-model conversations when "All" is selected.

Contributing
Contributions are welcome! Fork the repository, make changes, and submit a pull request.
License
MIT License. See LICENSE for details.
