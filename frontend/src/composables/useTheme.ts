import { ref, computed, onMounted, onUnmounted } from 'vue';

export type ThemeMode = 'auto' | 'dark' | 'light';
export type ResolvedTheme = 'dark' | 'light';

const STORAGE_KEY = 'nujin_theme_mode';

const themeMode = ref<ThemeMode>('auto');
const systemTheme = ref<ResolvedTheme>('dark');

const resolveSystemTheme = (): ResolvedTheme => {
  if (typeof window !== 'undefined' && window.matchMedia) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return 'dark';
};

const activeTheme = computed<ResolvedTheme>(() => {
  if (themeMode.value === 'auto') {
    return systemTheme.value;
  }
  return themeMode.value;
});

const isDark = computed(() => activeTheme.value === 'dark');

const applyThemeToDOM = (theme: ResolvedTheme) => {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', theme);
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }
};

let mediaQuery: MediaQueryList | null = null;
let initialized = false;

export function useTheme() {
  const initTheme = () => {
    if (initialized) return;
    initialized = true;

    // Check localStorage
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem(STORAGE_KEY) as ThemeMode | null;
      if (saved === 'auto' || saved === 'dark' || saved === 'light') {
        themeMode.value = saved;
      } else {
        themeMode.value = 'auto';
      }

      systemTheme.value = resolveSystemTheme();
      applyThemeToDOM(activeTheme.value);

      if (window.matchMedia) {
        mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
        mediaQuery.addEventListener('change', (e) => {
          systemTheme.value = e.matches ? 'dark' : 'light';
          if (themeMode.value === 'auto') {
            applyThemeToDOM(systemTheme.value);
          }
        });
      }
    }
  };

  const setThemeMode = (mode: ThemeMode) => {
    themeMode.value = mode;
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem(STORAGE_KEY, mode);
    }
    applyThemeToDOM(activeTheme.value);
  };

  const cycleTheme = () => {
    if (themeMode.value === 'auto') {
      setThemeMode('dark');
    } else if (themeMode.value === 'dark') {
      setThemeMode('light');
    } else {
      setThemeMode('auto');
    }
  };

  initTheme();

  return {
    themeMode,
    activeTheme,
    isDark,
    setThemeMode,
    cycleTheme,
  };
}
