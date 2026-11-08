// VitePress 官方文档配置 (Coolify 架构风格 + 中英双语支持)
import { defineConfig } from 'vitepress'

export default defineConfig({
  cleanUrls: true,
  locales: {
    root: {
      label: '简体中文',
      lang: 'zh-CN',
      title: "AstrBot Resource Monitor 官方文档",
      description: "AstrBot Resource Monitor 是专为 AstrBot 打造的轻量级主机性能监控与可视化卡片告警插件。",
      themeConfig: {
        siteTitle: "AstrBot 监控插件",
        nav: [
          { text: '官网首页', link: '/' },
          { text: '快速入门', link: '/docs/' },
          { text: '系统架构', link: '/docs/architecture' },
          { text: '配置指南', link: '/docs/configuration' },
          { text: '常见问题', link: '/docs/faq' },
          { text: 'GitHub', link: 'https://github.com/CyberNova2333/astrbot-resource-monitor' },
        ],
        sidebar: [
          {
            text: '快速入门',
            items: [
              { text: '项目概览与上手', link: '/docs/' },
            ]
          },
          {
            text: '系统架构',
            items: [
              { text: '架构设计与全景图', link: '/docs/architecture' },
            ]
          },
          {
            text: '配置与实践',
            items: [
              { text: '配置与使用指南', link: '/docs/configuration' },
            ]
          },
          {
            text: '运维与支持',
            items: [
              { text: '常见问题与排错', link: '/docs/faq' },
            ]
          }
        ],
        outline: { level: [2, 3], label: '本页目录' },
        docFooter: { prev: '上一页', next: '下一页' },
      }
    },
    en: {
      label: 'English',
      lang: 'en-US',
      link: '/en/',
      title: "AstrBot Resource Monitor Documentation",
      description: "AstrBot Resource Monitor is a lightweight host performance monitoring and visual card alerting plugin designed for AstrBot.",
      themeConfig: {
        siteTitle: "AstrBot Monitor",
        nav: [
          { text: 'Home', link: '/en/' },
          { text: 'Quick Start', link: '/en/docs/' },
          { text: 'Architecture', link: '/en/docs/architecture' },
          { text: 'Configuration', link: '/en/docs/configuration' },
          { text: 'FAQ', link: '/en/docs/faq' },
          { text: 'GitHub', link: 'https://github.com/CyberNova2333/astrbot-resource-monitor' },
        ],
        sidebar: [
          {
            text: 'Quick Start',
            items: [
              { text: 'Overview & Getting Started', link: '/en/docs/' },
            ]
          },
          {
            text: 'Architecture',
            items: [
              { text: 'Architecture Design', link: '/en/docs/architecture' },
            ]
          },
          {
            text: 'Configuration & Practice',
            items: [
              { text: 'Configuration Guide', link: '/en/docs/configuration' },
            ]
          },
          {
            text: 'Operations & Support',
            items: [
              { text: 'FAQ & Diagnostics', link: '/en/docs/faq' },
            ]
          }
        ],
        outline: { level: [2, 3], label: 'On this page' },
        docFooter: { prev: 'Previous page', next: 'Next page' },
      }
    }
  },
  themeConfig: {
    search: { provider: 'local' },
  }
})
