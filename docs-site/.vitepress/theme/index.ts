import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import Layout from './Layout.vue'
import './style.css'

const theme: Theme = {
  extends: DefaultTheme,
  Layout,
  enhanceApp({ router }) {
    if (typeof window === 'undefined') return
    // 动效加载失败时仍保留完整的阅读与外观切换功能。
    void import('./toggle')
      .then(({ setupAppearanceToggle }) => setupAppearanceToggle())
      .catch(() => undefined)
    void Promise.all([import('./vendor/animejs/anime.esm.min.js'), import('./motion')])
      .then(([anime, { setupDocsMotion }]) => setupDocsMotion(router, anime))
      .catch(() => undefined)
  },
}

export default theme
