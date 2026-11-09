export const STORAGE_KEY_USER_LANG = 'cbnv_user_lang';

/**
 * 检测访客浏览器首选语言。
 * 若首选或支持列表中包含英文（en-XX），返回 'en'；
 * 若包含中文（zh-XX），返回 'zh'；
 * 无法识别（如法文、日文、德文等或其他未知语言）时，按需求严格默认为中文 'zh'。
 */
export function detectBrowserLanguage(): 'en' | 'zh' {
  if (typeof navigator === 'undefined') return 'zh';
  const langs =
    navigator.languages && navigator.languages.length
      ? navigator.languages
      : [navigator.language || (navigator as any).userLanguage || ''];

  for (const lang of langs) {
    if (!lang || typeof lang !== 'string') continue;
    const lower = lang.trim().toLowerCase();
    if (lower.startsWith('en')) return 'en';
    if (lower.startsWith('zh')) return 'zh';
  }
  return 'zh'; // 无法识别时默认为中文
}

/**
 * 判断指定路径是否属于英文语言分区。
 */
export function isEnglishPath(path: string): boolean {
  if (!path) return false;
  return path === '/en' || path === '/en/' || path.startsWith('/en/');
}

/**
 * 将相对路径在中文路径与英文路径之间转换。
 */
export function getTargetRedirectUrl(
  targetLang: 'en' | 'zh',
  currentPath: string,
  base: string = '/'
): string | null {
  const normalizedBase = base.startsWith('/')
    ? base.endsWith('/')
      ? base
      : base + '/'
    : '/' + base + '/';

  let relPath = currentPath;
  if (currentPath.startsWith(normalizedBase)) {
    relPath = '/' + currentPath.slice(normalizedBase.length);
  }

  const isEn = isEnglishPath(relPath);
  let targetRelPath = relPath;

  if (targetLang === 'en' && !isEn) {
    if (relPath === '/' || relPath === '/index.html' || relPath === '') {
      targetRelPath = '/en/';
    } else {
      targetRelPath =
        '/en' + (relPath.startsWith('/') ? relPath : '/' + relPath);
    }
  } else if (targetLang === 'zh' && isEn) {
    if (
      relPath === '/en' ||
      relPath === '/en/' ||
      relPath === '/en/index.html'
    ) {
      targetRelPath = '/';
    } else {
      targetRelPath = relPath.replace(/^\/en(\/|$)/, '/');
      if (!targetRelPath) targetRelPath = '/';
    }
  } else {
    return null; // 无需重定向
  }

  const basePrefix = normalizedBase.slice(0, -1);
  const search = typeof window !== 'undefined' ? window.location.search : '';
  const hash = typeof window !== 'undefined' ? window.location.hash : '';
  return basePrefix + targetRelPath + search + hash;
}

/**
 * 执行初次进入或带存储偏好的语言自动路由导流。
 */
export function checkAndApplyLanguageRedirect(base: string = '/'): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const saved = localStorage.getItem(STORAGE_KEY_USER_LANG);
    let targetLang: 'en' | 'zh';
    if (saved === 'en' || saved === 'zh') {
      targetLang = saved;
    } else {
      // 首次访问：根据浏览器语言自动选择，无法识别默认为中文
      targetLang = detectBrowserLanguage();
      localStorage.setItem(STORAGE_KEY_USER_LANG, targetLang);
    }

    const currentPath = window.location.pathname;
    const redirectUrl = getTargetRedirectUrl(targetLang, currentPath, base);
    if (redirectUrl && redirectUrl !== currentPath) {
      window.location.replace(redirectUrl);
      return true;
    }
  } catch {
    // 捕获 localStorage 限制或异常
  }
  return false;
}

let isListenerAttached = false;

/**
 * 监听 VitePress 顶栏与移动端下拉菜单中的语言切换点击，持久化用户偏好。
 */
export function setupLanguageSwitcherListener(): void {
  if (typeof document === 'undefined' || isListenerAttached) return;
  isListenerAttached = true;

  document.addEventListener(
    'click',
    (event) => {
      const target = event.target;
      if (!target || !(target instanceof Element)) return;
      const link = target.closest('a');
      if (!link) return;

      const inTranslationMenu = !!link.closest(
        '.VPNavBarTranslations, .VPNavScreenTranslations, .VPNavBarMenuLink, .VPNavScreenMenuLink'
      );
      const hreflang = (
        link.getAttribute('hreflang') ||
        link.getAttribute('lang') ||
        ''
      ).toLowerCase();
      const href = link.getAttribute('href') || '';

      if (
        inTranslationMenu ||
        hreflang.startsWith('en') ||
        hreflang.startsWith('zh')
      ) {
        try {
          if (
            hreflang.startsWith('en') ||
            href.includes('/en/') ||
            href.endsWith('/en')
          ) {
            localStorage.setItem(STORAGE_KEY_USER_LANG, 'en');
          } else if (
            hreflang.startsWith('zh') ||
            (!href.includes('/en/') && !href.endsWith('/en'))
          ) {
            localStorage.setItem(STORAGE_KEY_USER_LANG, 'zh');
          }
        } catch {}
      }
    },
    true // capture 阶段触发，确保在路由跳转前写入
  );
}

/**
 * 路由变化时，若用户发生了跨语言分区跳转，同步更新本地偏好。
 */
export function syncLanguageOnRoute(currentPath: string): void {
  if (typeof window === 'undefined') return;
  try {
    const isEn = isEnglishPath(currentPath);
    const expectedLang = isEn ? 'en' : 'zh';
    const saved = localStorage.getItem(STORAGE_KEY_USER_LANG);
    if (saved !== expectedLang) {
      localStorage.setItem(STORAGE_KEY_USER_LANG, expectedLang);
    }
  } catch {}
}
