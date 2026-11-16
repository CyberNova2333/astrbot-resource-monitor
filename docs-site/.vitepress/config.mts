import { defineConfig } from 'vitepress'

export default defineConfig({
  cleanUrls: true,
  locales: {
    root: {
      label: '简体中文',
      lang: 'zh-CN',
      title: 'AstrBot Resource Monitor 文档',
      description: '面向 AstrBot 的定时资源分发线路探测插件文档：配置发现、HTTP Range 分片、MD5 校验、热更包与 TLS 证书有效期监控及告警投递。',
      themeConfig: {
        siteTitle: 'Resource Monitor',
        nav: [
          { text: '首页', link: '/' },
          { text: '起步与配置', link: '/docs/' },
          { text: '契约与扩展', link: '/docs/contracts' },
          { text: '原理与导览', link: '/docs/architecture' },
          { text: 'GitHub', link: 'https://github.com/CyberNova2333/astrbot-resource-monitor' },
        ],
        sidebar: [
          {
            text: '起步与配置部署',
            items: [
              { text: '概览、边界与插件安装', link: '/docs/' },
              { text: '配置源、参数矩阵与排错 FAQ', link: '/docs/configuration' },
            ],
          },
          {
            text: '接口与扩展契约',
            items: [
              { text: '探针契约、安全护栏与扩展点', link: '/docs/contracts' },
            ],
          },
          {
            text: '原理与源码导览',
            items: [
              { text: '运行原理、交互拓扑与架构决策', link: '/docs/architecture' },
            ],
          },
        ],
        outline: { level: [2, 3], label: '本页目录' },
        docFooter: { prev: '上一页', next: '下一页' },
      },
    },
    en: {
      label: 'English',
      lang: 'en-US',
      link: '/en/',
      title: 'AstrBot Resource Monitor Docs',
      description: 'Scheduled resource-distribution route probe plugin for AstrBot: config/manifest discovery, HTTP Range chunks, MD5 checksums, hot-update packages, TLS expiry, and multi-channel alerting.',
      themeConfig: {
        siteTitle: 'Resource Monitor',
        nav: [
          { text: 'Home', link: '/en/' },
          { text: 'Quick Start & Config', link: '/en/docs/' },
          { text: 'Contracts & Extensions', link: '/en/docs/contracts' },
          { text: 'Architecture & Decisions', link: '/en/docs/architecture' },
          { text: 'GitHub', link: 'https://github.com/CyberNova2333/astrbot-resource-monitor' },
        ],
        sidebar: [
          {
            text: 'Getting Started & Config',
            items: [
              { text: 'Overview, Boundaries & Install', link: '/en/docs/' },
              { text: 'Config Matrix, Sources & FAQ', link: '/en/docs/configuration' },
            ],
          },
          {
            text: 'Contracts & Extensions',
            items: [
              { text: 'Probes, Security Gates & Extension Points', link: '/en/docs/contracts' },
            ],
          },
          {
            text: 'Architecture & Decisions',
            items: [
              { text: 'Execution Flow, Topology & ADRs', link: '/en/docs/architecture' },
            ],
          },
        ],
        outline: { level: [2, 3], label: 'On this page' },
        docFooter: { prev: 'Previous page', next: 'Next page' },
      },
    },
  },
  themeConfig: {
    search: { provider: 'local' },
  },
})
