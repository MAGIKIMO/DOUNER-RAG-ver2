/* Only public UI assets are cached. API responses and user data never enter CacheStorage. */
'use strict';
const CACHE = 'donga-ui-v3';
const ASSETS = ['/index.html','/chat.html','/meals.html','/install.html','/offline.html',
  '/style.css','/student.css','/meals.css','/mobile.css','/app.js','/student.js','/meals.js','/pwa.js',
  '/manifest.webmanifest','/icons/douner-logo.svg','/icons/favicon-32.png','/icons/icon-192.png','/icons/icon-512.png','/icons/apple-touch-icon.png'];
const ALLOWED = new Set(ASSETS);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS.map(url => new Request(url, {cache:'reload'})))));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('donga-ui-') && key !== CACHE).map(key => caches.delete(key)))));
});
self.addEventListener('message', event => {
  if (event.data?.type === 'APPLY_UPDATE') self.skipWaiting();
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  const path = url.pathname === '/' ? '/index.html' : url.pathname;
  if (!ALLOWED.has(path)) return;
  // Network first keeps normal web visits fresh. Query variants never become cache keys.
  event.respondWith((async () => {
    try {
      const response = await fetch(event.request);
      if (response.ok) return response;
      if (event.request.mode !== 'navigate') return response;
    } catch { /* Use the install-time static shell only. */ }
    const cache = await caches.open(CACHE);
    return await cache.match(path) || await cache.match('/offline.html');
  })());
});
