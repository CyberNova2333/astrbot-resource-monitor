// VitePress default theme; content lives in repo-docs.
import { guideLinks } from './guide-links.mts'

const pages = {
  "change-log.md": "change-log",
  "code-map.md": "code-map",
  "README.md": "",
  "references/quality-review.md": "references/quality-review",
  "references/source-evidence.md": "references/source-evidence",
  "walkthroughs/one-real-run.md": "walkthroughs/one-real-run"
}

export default {
  lang: 'zh-CN',
  title: "AstrBot Resource Monitor · 源码指南",
  cleanUrls: true,
  markdown: { config: guideLinks(pages) },
  themeConfig: {
    siteTitle: "资源监控",
    nav: [
      { text: '官网首页', link: '/' },
      { text: '文档指南', link: '/walkthroughs/one-real-run' },
      { text: '代码地图', link: '/code-map' },
      { text: 'GitHub', link: 'https://github.com/CyberNova2333/astrbot-resource-monitor' },
    ],
    sidebar: [{ text: '源码指南', items: [
  {
    "text": "阅读路径",
    "link": "/"
  },
  {
    "text": "一条真实主流程",
    "link": "/walkthroughs/one-real-run"
  },
  {
    "text": "代码地图",
    "link": "/code-map"
  },
  {
    "text": "源码证据",
    "link": "/references/source-evidence"
  },
  {
    "text": "阅读质量审计",
    "link": "/references/quality-review"
  },
  {
    "text": "指南变更",
    "link": "/change-log"
  }
] }],
    search: { provider: 'local' },
    outline: { level: [2, 3], label: '本页目录' },
    docFooter: { prev: '上一页', next: '下一页' },
  },
}
