import { ref, onMounted } from 'vue';

const isInstallable = ref(false);
const isStandalone = ref(false);
let deferredPrompt: any = null;

export function usePwa() {
  const checkStandalone = () => {
    if (typeof window === 'undefined') return false;
    const isStandaloneMedia = window.matchMedia('(display-mode: standalone)').matches;
    const isIosStandalone = (window.navigator as any)?.standalone === true;
    return isStandaloneMedia || isIosStandalone;
  };

  const installPwa = async () => {
    if (!deferredPrompt) return;
    try {
      deferredPrompt.prompt();
      const { outcome } = await deferredPrompt.userChoice;
      if (outcome === 'accepted') {
        isInstallable.value = false;
        deferredPrompt = null;
      }
    } catch (e) {
      console.warn('[PWA] Install prompt failed:', e);
    }
  };

  onMounted(() => {
    if (typeof window === 'undefined') return;

    isStandalone.value = checkStandalone();

    window.addEventListener('beforeinstallprompt', (e: Event) => {
      e.preventDefault();
      deferredPrompt = e;
      isInstallable.value = true;
    });

    window.addEventListener('appinstalled', () => {
      isInstallable.value = false;
      isStandalone.value = true;
      deferredPrompt = null;
    });
  });

  return {
    isInstallable,
    isStandalone,
    installPwa,
  };
}
