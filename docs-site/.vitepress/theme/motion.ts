import type { Router } from 'vitepress';

interface AnimeAnimation {
  pause(): void;
  play(): void;
}

interface AnimeTimeline extends AnimeAnimation {
  add(
    targets: HTMLElement[],
    parameters: Record<string, unknown>,
    position?: number | string
  ): AnimeTimeline;
}

interface AnimeScope {
  revert(): void;
}

interface AnimeModule {
  animate(
    targets: HTMLElement | HTMLElement[],
    parameters: Record<string, unknown>
  ): AnimeAnimation;
  createTimeline(parameters: Record<string, unknown>): AnimeTimeline;
  createScope(parameters: Record<string, unknown>): {
    add(
      callback: (self: { matches: { reduced: boolean } }) => void
    ): AnimeScope;
  };
  stagger(duration: number): unknown;
}

export function setupDocsMotion(router: Router, anime: AnimeModule) {
  const { animate, createTimeline, createScope, stagger } = anime;
  let scope: AnimeScope | undefined;
  let observer: IntersectionObserver | undefined;
  let entrance: AnimeTimeline | undefined;
  let loops: AnimeAnimation[] = [];
  let reveals = new Set<AnimeAnimation>();
  let frame: number | undefined;
  let onVisibilityChange: (() => void) | undefined;

  const query = (selector: string, root: ParentNode = document) =>
    Array.from(root.querySelectorAll<HTMLElement>(selector));

  const clearInline = (element: HTMLElement) => {
    element.style.removeProperty('transform');
    element.style.removeProperty('opacity');
    element.style.removeProperty('clip-path');
  };

  function cleanup() {
    if (frame !== undefined) cancelAnimationFrame(frame);
    frame = undefined;
    scope?.revert();
    scope = undefined;
    entrance?.pause();
    entrance = undefined;
    observer?.disconnect();
    observer = undefined;
    for (const animation of loops) animation.pause();
    loops = [];
    for (const animation of reveals) animation.pause();
    reveals.clear();
    if (onVisibilityChange)
      document.removeEventListener('visibilitychange', onVisibilityChange);
    onVisibilityChange = undefined;
    document.documentElement.classList.remove('motion-on');

    // 清除可能残留的内联动画样式，确保不论何时切换模式，正文所有元素（标题、代码块、表格等）均保持 100% 不透明度正常呈现
    const animatedElements = query(
      [
        '.VPNavBar',
        '.adv-docs-deco__band',
        '.vp-doc h1',
        '.vp-doc h2',
        '.vp-doc h3',
        '.vp-doc .custom-block',
        '.vp-doc table',
        '.vp-doc div[class*="language-"]',
        '.vp-doc blockquote',
        '.VPFeature',
        '.vp-doc .content-container > *',
        '.VPHero .main > *',
      ].join(', ')
    );
    for (const el of animatedElements) {
      clearInline(el);
    }
  }

  function run() {
    cleanup();
    // 严肃模式下停用华丽悬浮动效，保持克制、纯净与高响应速度
    if (document.documentElement.classList.contains('serious-mode')) {
      return;
    }

    scope = createScope({
      mediaQueries: { reduced: '(prefers-reduced-motion: reduce)' },
    }).add((self) => {
      if (self.matches.reduced) {
        for (const heading of query('.vp-doc h2'))
          heading.classList.add('adv-docs-bar-in');
        return;
      }
      document.documentElement.classList.add('motion-on');

      const orbs = query('.adv-docs-deco__orb');
      if (orbs.length) {
        const float = animate(orbs, {
          y: (_element: HTMLElement, index: number) => [
            0,
            index % 2 ? -12 : 10,
          ],
          opacity: [0.82, 1],
          duration: (_element: HTMLElement, index: number) =>
            6200 + index * 1400,
          ease: 'inOutSine',
          loop: true,
          alternate: true,
          autoplay: false,
        });
        loops.push(float);
        onVisibilityChange = () => {
          if (document.hidden) float.pause();
          else float.play();
        };
        document.addEventListener('visibilitychange', onVisibilityChange);
        if (!document.hidden) float.play();
      }

      const nav = query('.VPNavBar');
      const band = query('.adv-docs-deco__band');
      const hero = query('.VPHero .main > *').slice(0, 8);
      const isHome = hero.length > 0;

      // 仅在官网首页或明确入场目标存在时执行入场时间线
      // 关键修复：入场元素在时间线启动时立即设为初始透明状态，避免“字在开始前已到位再抽搐”的闪烁
      const entranceTargets = isHome
        ? [...nav, ...band, ...hero]
        : [...nav, ...band];
      for (const el of entranceTargets) {
        el.style.opacity = '0';
        el.style.transform = 'translateY(10px)';
      }

      entrance = createTimeline({
        defaults: { ease: 'outCubic', duration: 750 },
        onComplete: () => {
          for (const element of entranceTargets) clearInline(element);
        },
      });

      if (nav.length)
        entrance.add(nav, { opacity: [0, 1], y: [-8, 0], duration: 650 }, 0);
      if (band.length)
        entrance.add(
          band,
          { scaleX: [0, 1], duration: 900, ease: 'outCubic' },
          50
        );
      if (hero.length) {
        entrance.add(
          hero,
          { opacity: [0, 1], y: [12, 0], delay: stagger(90), duration: 750 },
          100
        );
      }

      // 文档正文部分：仅对首屏视口下方（未入屏）的区块在滚动进入时平滑淡入，绝不二次重复触发已渲染元素
      const selector = [
        '.vp-doc h2',
        '.vp-doc h3',
        '.vp-doc .custom-block',
        '.vp-doc table',
        '.vp-doc div[class*="language-"]',
        '.vp-doc blockquote',
        '.VPFeature',
      ].join(', ');

      const viewHeight = window.innerHeight || 800;
      const elements = query(selector).filter((element) => {
        if (element.closest('.VPSidebar') !== null) return false;
        // 如果元素已经在视口首屏内，直接保持静止可见，绝不后置触发动画导致抽搐
        const { top } = element.getBoundingClientRect();
        return top >= viewHeight * 0.9;
      });

      if (elements.length) {
        observer = new IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              if (!entry.isIntersecting) continue;
              const element = entry.target as HTMLElement;
              observer?.unobserve(element);
              if (element.matches('.vp-doc h2'))
                element.classList.add('adv-docs-bar-in');
              // 初始设为 0 并平滑升起，时长放缓至 700ms
              element.style.opacity = '0';
              element.style.transform = 'translateY(12px)';
              const animation = animate(element, {
                opacity: [0, 1],
                y: [12, 0],
                duration: 700,
                ease: 'outCubic',
                onComplete: () => {
                  clearInline(element);
                  reveals.delete(animation);
                },
              });
              reveals.add(animation);
            }
          },
          { threshold: 0.1, rootMargin: '0px 0px -40px 0px' }
        );
        for (const element of elements) observer.observe(element);
      }

      for (const heading of query('.vp-doc h2')) {
        const { top: headingTop } = heading.getBoundingClientRect();
        if (headingTop < viewHeight) heading.classList.add('adv-docs-bar-in');
      }
    });
  }

  function schedule() {
    if (frame !== undefined) cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      frame = undefined;
      run();
    });
  }

  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', schedule, { once: true });
  else schedule();
  router.onAfterRouteChanged = schedule;

  // 监听简约模式切换：只在 serious-mode 类名实际变化时重新调度，避免 classList.add('motion-on') 引起无限循环重绘
  let lastSerious =
    typeof document !== 'undefined'
      ? document.documentElement.classList.contains('serious-mode')
      : false;
  new MutationObserver(() => {
    const currentSerious =
      document.documentElement.classList.contains('serious-mode');
    if (currentSerious !== lastSerious) {
      lastSerious = currentSerious;
      schedule();
    }
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['class'],
  });
}
