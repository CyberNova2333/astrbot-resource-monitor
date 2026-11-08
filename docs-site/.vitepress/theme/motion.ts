import type { Router } from 'vitepress'

interface AnimeAnimation {
  pause(): void
  play(): void
}

interface AnimeTimeline extends AnimeAnimation {
  add(targets: HTMLElement[], parameters: Record<string, unknown>, position?: number | string): AnimeTimeline
}

interface AnimeScope {
  revert(): void
}

interface AnimeModule {
  animate(targets: HTMLElement | HTMLElement[], parameters: Record<string, unknown>): AnimeAnimation
  createTimeline(parameters: Record<string, unknown>): AnimeTimeline
  createScope(parameters: Record<string, unknown>): {
    add(callback: (self: { matches: { reduced: boolean } }) => void): AnimeScope
  }
  stagger(duration: number): unknown
}

export function setupDocsMotion(router: Router, anime: AnimeModule) {
  const { animate, createTimeline, createScope, stagger } = anime
  let scope: AnimeScope | undefined
  let observer: IntersectionObserver | undefined
  let entrance: AnimeTimeline | undefined
  let loops: AnimeAnimation[] = []
  let reveals = new Set<AnimeAnimation>()
  let frame: number | undefined
  let onVisibilityChange: (() => void) | undefined

  const query = (selector: string, root: ParentNode = document) =>
    Array.from(root.querySelectorAll<HTMLElement>(selector))

  const clearInline = (element: HTMLElement) => {
    element.style.removeProperty('transform')
    element.style.removeProperty('opacity')
    element.style.removeProperty('clip-path')
  }

  function cleanup() {
    if (frame !== undefined) cancelAnimationFrame(frame)
    frame = undefined
    scope?.revert()
    scope = undefined
    entrance?.pause()
    entrance = undefined
    observer?.disconnect()
    observer = undefined
    for (const animation of loops) animation.pause()
    loops = []
    for (const animation of reveals) animation.pause()
    reveals.clear()
    if (onVisibilityChange) document.removeEventListener('visibilitychange', onVisibilityChange)
    onVisibilityChange = undefined
    document.documentElement.classList.remove('motion-on')
  }

  function run() {
    cleanup()
    // 严肃模式下停用华丽悬浮动效，保持克制、纯净与高响应速度
    if (document.documentElement.classList.contains('serious-mode')) {
      return
    }

    scope = createScope({ mediaQueries: { reduced: '(prefers-reduced-motion: reduce)' } }).add((self) => {
      if (self.matches.reduced) {
        for (const heading of query('.vp-doc h2')) heading.classList.add('adv-docs-bar-in')
        return
      }
      document.documentElement.classList.add('motion-on')

      const orbs = query('.adv-docs-deco__orb')
      if (orbs.length) {
        const float = animate(orbs, {
          y: (_element: HTMLElement, index: number) => [0, index % 2 ? -12 : 10],
          opacity: [0.82, 1],
          duration: (_element: HTMLElement, index: number) => 4600 + index * 1000,
          ease: 'inOutSine',
          loop: true,
          alternate: true,
          autoplay: false,
        })
        loops.push(float)
        onVisibilityChange = () => {
          if (document.hidden) float.pause()
          else float.play()
        }
        document.addEventListener('visibilitychange', onVisibilityChange)
        if (!document.hidden) float.play()
      }

      const nav = query('.VPNavBar')
      const band = query('.adv-docs-deco__band')
      const title = query('.vp-doc h1')
      const blocks = query('.vp-doc .content-container > *').slice(0, 12)
      const hero = query('.VPHero .main > *').slice(0, 8)
      const entranceTargets = [...nav, ...band, ...title, ...blocks, ...hero]
      entrance = createTimeline({
        defaults: { ease: 'outQuart', duration: 300 },
        onComplete: () => {
          for (const element of entranceTargets) clearInline(element)
        },
      })
      if (nav.length) entrance.add(nav, { opacity: [0, 1], y: [-10, 0] }, 0)
      if (band.length) entrance.add(band, { scaleX: [0, 1], duration: 700, ease: 'outQuint' }, 60)
      if (title.length) {
        entrance.add(title, {
          opacity: [0, 1],
          y: [10, 0],
          clipPath: ['inset(0 100% 0 0)', 'inset(0 0% 0 0)'],
          duration: 460,
        }, 100)
      }
      if (hero.length) entrance.add(hero, { opacity: [0, 1], y: [14, 0], delay: stagger(48) }, '<+=100')
      if (blocks.length) entrance.add(blocks, { opacity: [0, 1], y: [12, 0], delay: stagger(48) }, title.length ? '<+=180' : 140)

      const selector = [
        '.vp-doc h2',
        '.vp-doc h3',
        '.vp-doc .custom-block',
        '.vp-doc table',
        '.vp-doc div[class*="language-"]',
        '.vp-doc blockquote',
        '.VPFeature',
      ].join(', ')
      const elements = query(selector).filter((element) => element.closest('.VPSidebar') === null)
      if (elements.length) {
        observer = new IntersectionObserver((entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue
            const element = entry.target as HTMLElement
            observer?.unobserve(element)
            if (element.matches('.vp-doc h2')) element.classList.add('adv-docs-bar-in')
            const animation = animate(element, {
              opacity: [0, 1],
              y: [16, 0],
              duration: 320,
              ease: 'outQuart',
              onComplete: () => {
                clearInline(element)
                reveals.delete(animation)
              },
            })
            reveals.add(animation)
          }
        }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' })
        for (const element of elements) observer.observe(element)
      }
      for (const heading of query('.vp-doc h2')) {
        if (heading.getBoundingClientRect().top < window.innerHeight) heading.classList.add('adv-docs-bar-in')
      }
    })
  }

  function schedule() {
    if (frame !== undefined) cancelAnimationFrame(frame)
    frame = requestAnimationFrame(() => {
      frame = undefined
      run()
    })
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', schedule, { once: true })
  else schedule()
  router.onAfterRouteChanged = schedule

  // 监听严肃模式切换
  new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'attributes' && m.attributeName === 'class') {
        schedule()
      }
    }
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
}
