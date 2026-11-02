import { createApp } from 'vue';
import App from './App.vue';
import './index.css';
import { registerSW } from 'virtual:pwa-register';

// Register PWA service worker with auto-update
const updateSW = registerSW({
  immediate: true,
  onNeedRefresh() {
    console.log('[PWA] New content available, updating service worker...');
    updateSW(true);
  },
  onOfflineReady() {
    console.log('[PWA] NujinAI Cockpit ready for offline operation');
  },
  onRegistered(r) {
    console.log('[PWA] Service Worker registered successfully:', r?.scope);
  },
  onRegisterError(error) {
    console.warn('[PWA] Service Worker registration failed:', error);
  }
});

const app = createApp(App);
app.mount('#app');
