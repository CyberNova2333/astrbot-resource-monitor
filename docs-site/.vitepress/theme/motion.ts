import type { Router } from "vitepress";

interface AnimeAnimation {
  pause(): void;
  play(): void;
}

interface AnimeTimeline extends AnimeAnimation {
  add(
    targets: HTMLElement[],
    parameters: Record<string, unknown>,
    position?: number | string,
  ): AnimeTimeline;
}

interface AnimeScope {
  revert(): void;
}

interface AnimeModule {
  animate(
    targets: HTMLElement | HTMLElement[],
    parameters: Record<string, unknown>,
  ): AnimeAnimation;
  createTimeline(parameters: Record<string, unknown>): AnimeTimeline;
  createScope(parameters: Record<string, unknown>): {
    add(
      callback: (self: { matches: { reduced: boolean } }) => void,
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
    element.style.removeProperty("transform");
    element.style.removeProperty("opacity");
    element.style.removeProperty("clip-path");
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
      document.removeEventListener("visibilitychange", onVisibilityChange);
    onVisibilityChange = undefined;
    document.documentElement.classList.remove("motion-on");

    // 清除可能残留的内联动画样式，确保不论何时切换模式，正文所有元素（标题、代码块、表格等）均保持 100% 不透明度正常呈现
    const animatedElements = query(
      [
        ".VPNavBar",
        ".adv-docs-deco__band",
        ".vp-doc h1",
        ".vp-doc h2",
        ".vp-doc h3",
        ".vp-doc .custom-block",
        ".vp-doc table",
        '.vp-doc div[class*="language-"]',
        ".vp-doc blockquote",
        ".VPFeature",
        ".vp-doc .content-container > *",
        ".VPHero .main > *",
      ].join(", "),
    );
    for (const el of animatedElements) {
      clearInline(el);
    }
  }

  function run() {
    cleanup();
    // 严肃模式下停用华丽悬浮动效，保持克制、纯净与高响应速度
    if (document.documentElement.classList.contains("serious-mode")) {
      return;
    }

    scope = createScope({
      mediaQueries: { reduced: "(prefers-reduced-motion: reduce)" },
    }).add((self) => {
      if (self.matches.reduced) {
        for (const heading of query(".vp-doc h2"))
          heading.classList.add("adv-docs-bar-in");
        return;
      }
      document.documentElement.classList.add("motion-on");

      const orbs = query(".adv-docs-deco__orb");
      if (orbs.length) {
        const float = animate(orbs, {
          y: (_element: HTMLElement, index: number) => [
            0,
            index % 2 ? -12 : 10,
          ],
          opacity: [0.82, 1],
          duration: (_element: HTMLElement, index: number) =>
            7500 + index * 1800,
          ease: "inOutSine",
          loop: true,
          alternate: true,
          autoplay: false,
        });
        loops.push(float);
        onVisibilityChange = () => {
          if (document.hidden) float.pause();
          else float.play();
        };
        document.addEventListener("visibilitychange", onVisibilityChange);
        if (!document.hidden) float.play();
      }

      const nav = query(".VPNavBar");
      const band = query(".adv-docs-deco__band");

      // 背景装饰与顶栏入场平滑渐显（放慢动画速度，时长统一舒缓放慢至 1100ms）
      const entranceTargets = [...nav, ...band];
      entrance = createTimeline({
        defaults: { ease: "outCubic", duration: 1100 },
        onComplete: () => {
          for (const element of entranceTargets) clearInline(element);
        },
      });

      if (nav.length)
        entrance.add(nav, { opacity: [0.85, 1], duration: 900 }, 0);
      if (band.length)
        entrance.add(
          band,
          { scaleX: [0, 1], duration: 1100, ease: "outCubic" },
          50,
        );

      // 标题底线装饰指示器：滚动进入视口时平滑展开装饰横条，绝不破坏正文阅读透明度
      const headings = query(".vp-doc h2");
      if (headings.length) {
        observer = new IntersectionObserver(
          (entries) => {
            for (const entry of entries) {
              if (!entry.isIntersecting) continue;
              const element = entry.target as HTMLElement;
              observer?.unobserve(element);
              element.classList.add("adv-docs-bar-in");
            }
          },
          { threshold: 0.1, rootMargin: "0px 0px -40px 0px" },
        );
        for (const heading of headings) observer.observe(heading);
      }

      const viewHeight = window.innerHeight || 800;
      for (const heading of headings) {
        const { top: headingTop } = heading.getBoundingClientRect();
        if (headingTop < viewHeight) heading.classList.add("adv-docs-bar-in");
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

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", schedule, { once: true });
  else schedule();
  router.onAfterRouteChanged = schedule;

  // 监听简约模式切换：只在 serious-mode 类名实际变化时重新调度，避免 classList.add('motion-on') 引起无限循环重绘
  let lastSerious =
    typeof document !== "undefined"
      ? document.documentElement.classList.contains("serious-mode")
      : false;
  new MutationObserver(() => {
    const currentSerious =
      document.documentElement.classList.contains("serious-mode");
    if (currentSerious !== lastSerious) {
      lastSerious = currentSerious;
      schedule();
    }
  }).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class"],
  });
}
