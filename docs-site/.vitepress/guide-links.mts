import { posix } from 'node:path'

// Only resolve content links; the built-in VitePress theme is unmodified.
export function guideLinks(pages: Record<string, string>) {
  return (md: any) => {
    md.core.ruler.after('inline', 'repo-guide-links', (state: any) => {
      const source = state.env.frontmatter?.repoGuideSource
      if (typeof source !== 'string') return
      for (const token of state.tokens) {
        const children = token.children || []
        for (let i = 0; i < children.length; i++) {
          const child = children[i]
          if (child.type !== 'link_open') continue
          const href = child.attrGet('href')
          if (!href || /^(?:[a-z]+:|\/|#)/i.test(href)) continue
          const [file, fragment] = href.split('#', 2)
          const target = posix.normalize(posix.join(posix.dirname(source), decodeURIComponent(file)))
          if (target.startsWith('repo-docs/')) {
            const route = pages[target.slice('repo-docs/'.length)]
            if (route !== undefined) child.attrSet('href', '/' + route + (fragment ? '#' + fragment : ''))
          } else {
            const close = children.slice(i + 1).find((item: any) => item.type === 'link_close')
            if (!close) continue
            child.type = 'text'; child.tag = ''; child.nesting = 0; child.attrs = null; child.content = ''
            close.type = 'html_inline'; close.tag = ''; close.nesting = 0; close.attrs = null
            close.content = '（仓库文件：<code>' + md.utils.escapeHtml(target + (fragment ? '#' + fragment : '')) + '</code>）'
          }
        }
      }
    })
  }
}
